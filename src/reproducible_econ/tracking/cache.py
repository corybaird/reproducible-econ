import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

import pandas as pd

from reproducible_econ.tracking.fingerprint import sha256_file
from reproducible_econ.tracking.metadata import CacheArtifactMetadata

logger = logging.getLogger(__name__)


class StageCache:
    """Atomic parquet stage cache with metadata verification and retention pruning."""

    EMITTER_STAMP_FILENAME = "emitter_stamp.json"

    def __init__(self, cache_dir, retain_prior_fingerprints=2):
        self.cache_dir = Path(cache_dir)
        self.retain_prior_fingerprints = retain_prior_fingerprints

    def load_emitter_stamp(self, name, fingerprint, component_hashes=None):
        """Check whether an emitter stage is up to date; return (hit, stamp, miss_reason)."""
        stamp_path = self.cache_dir / name / self.EMITTER_STAMP_FILENAME
        if not stamp_path.is_file():
            return False, None, "no_cache"
        try:
            stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, None, "missing_metadata"
        if not isinstance(stamp, dict) or stamp.get("format_version") != CacheArtifactMetadata.FORMAT_VERSION:
            return False, None, "missing_metadata"
        if stamp.get("fingerprint") != fingerprint:
            prior = stamp.get("components")
            if isinstance(prior, dict) and component_hashes:
                changed = sorted(key for key, val in component_hashes.items() if prior.get(key) != val)
                if changed:
                    return False, None, f"fingerprint_changed: {', '.join(changed)}"
            return False, None, "fingerprint_changed"
        emitted_files = stamp.get("emitted_files")
        if not isinstance(emitted_files, dict) or not emitted_files:
            return False, None, "missing_output"
        for path_str, expected_digest in emitted_files.items():
            path = Path(path_str)
            if not path.is_file():
                return False, None, f"missing_output: {path.name}"
            if sha256_file(path) != expected_digest:
                return False, None, f"output_modified: {path.name}"
        return True, stamp, None

    def save_emitter_stamp(self, name, fingerprint, emitted_paths, component_hashes=None, claims_summary=None):
        """Atomically persist an emitter stage's input fingerprint and output file digests."""
        emitted_files = {}
        for raw_path in emitted_paths:
            path = Path(raw_path).resolve()
            if path.is_file():
                emitted_files[str(path)] = sha256_file(path)
        if not emitted_files:
            return None
        stage_dir = self.cache_dir / name
        stage_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "format_version": CacheArtifactMetadata.FORMAT_VERSION,
            "fingerprint": fingerprint,
            "components": dict(component_hashes or {}),
            "emitted_files": emitted_files,
        }
        if claims_summary is not None:
            payload["claims_summary"] = dict(claims_summary)
        stamp_path = stage_dir / self.EMITTER_STAMP_FILENAME
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-stamp-", suffix=".json", dir=stage_dir)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, indent=2, sort_keys=True))
            os.replace(tmp_path, stamp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
        return stamp_path

    def load(self, name, fingerprint, data, output_keys, component_hashes=None):
        """Attempt to load cached DataFrames; return (hit, miss_reason)."""
        stage_dir = self.cache_dir / name
        fp_dir = stage_dir / fingerprint
        if not fp_dir.is_dir():
            return False, self._classify_missing_fp(stage_dir, component_hashes)
        metadata_path = fp_dir / "metadata.json"
        if not metadata_path.is_file():
            return False, "missing_metadata"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "missing_metadata"
        if not isinstance(metadata, dict) or metadata.get("format_version") != CacheArtifactMetadata.FORMAT_VERSION:
            return False, "missing_metadata"
        artifacts = metadata.get("artifacts")
        if not isinstance(artifacts, dict):
            return False, "missing_metadata"
        missing = [key for key in output_keys if key not in artifacts or not (fp_dir / f"{key}.parquet").is_file()]
        if missing:
            return False, f"missing_artifact: {', '.join(missing)}"
        frames = {}
        for key in output_keys:
            path = fp_dir / f"{key}.parquet"
            expected = artifacts[key]
            if not CacheArtifactMetadata.validate_file_checksum(path, expected):
                return False, f"checksum_mismatch: {key}"
            try:
                frame = pd.read_parquet(path)
            except (OSError, ValueError):
                return False, f"metadata_mismatch: {key}"
            valid, reason = CacheArtifactMetadata.validate(frame, expected)
            if not valid:
                return False, f"{reason}: {key}"
            frames[key] = frame
        data.update(frames)
        return True, None

    def save(self, name, fingerprint, data, output_keys, component_hashes=None):
        """Atomically save DataFrames, metadata sidecar, and fingerprint summary."""
        stage_dir = self.cache_dir / name
        stage_dir.mkdir(parents=True, exist_ok=True)
        fp_dir = stage_dir / fingerprint
        tmp_dir = Path(tempfile.mkdtemp(prefix=".tmp-", dir=stage_dir))
        stale_dir = None
        try:
            artifacts_meta = {}
            persisted_frames = {}
            for key in output_keys:
                frame = data[key]
                if not isinstance(frame, pd.DataFrame):
                    raise TypeError(f"Cached output {key!r} for stage {name!r} must be a pandas DataFrame")
                parquet_path = tmp_dir / f"{key}.parquet"
                frame.to_parquet(parquet_path, index=True)
                persisted = pd.read_parquet(parquet_path)
                artifacts_meta[key] = CacheArtifactMetadata.build(persisted, file_path=parquet_path)
                persisted_frames[key] = persisted
            metadata = {"format_version": CacheArtifactMetadata.FORMAT_VERSION, "artifacts": artifacts_meta}
            (tmp_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
            (tmp_dir / "fingerprint_summary.json").write_text(json.dumps(dict(component_hashes or {}), indent=2, sort_keys=True), encoding="utf-8")
            if fp_dir.exists():
                stale_dir = stage_dir / f".stale-{fingerprint}-{os.getpid()}-{tmp_dir.name}"
                os.replace(fp_dir, stale_dir)
            os.replace(tmp_dir, fp_dir)
            data.update(persisted_frames)
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            if stale_dir is not None and stale_dir.exists():
                shutil.rmtree(stale_dir, ignore_errors=True)
        if self.retain_prior_fingerprints is not None:
            self._prune(stage_dir, keep=fp_dir.name)
        return fp_dir

    def _classify_missing_fp(self, stage_dir, component_hashes):
        prior_dirs = self._prior_fingerprint_dirs(stage_dir)
        if not prior_dirs:
            return "no_cache"
        if not component_hashes:
            return "fingerprint_changed"
        newest = prior_dirs[0]
        summary_path = newest / "fingerprint_summary.json"
        if not summary_path.is_file():
            return "fingerprint_changed"
        try:
            prior_summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "fingerprint_changed"
        if not isinstance(prior_summary, dict):
            return "fingerprint_changed"
        changed = sorted(key for key, val in component_hashes.items() if prior_summary.get(key) != val)
        if changed:
            return f"fingerprint_changed: {', '.join(changed)}"
        return "fingerprint_changed"

    @staticmethod
    def _prior_fingerprint_dirs(stage_dir):
        if not stage_dir.is_dir():
            return []
        dirs = [entry for entry in stage_dir.iterdir() if entry.is_dir() and not entry.name.startswith((".tmp-", ".stale-"))]
        return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)

    def _prune(self, stage_dir, keep):
        siblings = [entry for entry in self._prior_fingerprint_dirs(stage_dir) if entry.name != keep]
        limit = max(0, int(self.retain_prior_fingerprints))
        for obsolete in siblings[limit:]:
            shutil.rmtree(obsolete, ignore_errors=True)
