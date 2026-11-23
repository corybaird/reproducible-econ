import json
import os
import platform
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from reproducible_econ.tracking.fingerprint import (
    canonical_json_sha256,
    core_dependency_versions,
    sha256_file,
)
from reproducible_econ.tracking.metadata import CacheArtifactMetadata

MANIFEST_VERSION = "2"
MANIFEST_PACKAGES = ("pandas", "pyarrow", "pyyaml", "reproducible-econ", "matplotlib")


def summarize_artifact(value):
    """Build a compact provenance summary for a stage DataFrame or non-DataFrame artifact."""
    if isinstance(value, pd.DataFrame):
        return {
            "rows": len(value),
            "columns": [str(col) for col in value.columns],
            "frame_sha256": CacheArtifactMetadata.frame_sha256(value),
        }
    return {"type": type(value).__name__}


class RunManifest:
    """Track run-level and stage-level provenance and save atomically to JSON."""

    def __init__(self, config, config_path, no_cache=False, config_includes=None, targets=None, run_timestamp=None, git_cwd=None):
        self._git_cwd = git_cwd
        now = datetime.now(UTC)
        self.run_timestamp = run_timestamp or now.strftime("%Y%m%dT%H%M%SZ")
        extra_packages = (config.get("manifest") or {}).get("extra_packages") or []
        packages = tuple(dict.fromkeys([*MANIFEST_PACKAGES, *extra_packages]))
        self.data = {
            "manifest_version": MANIFEST_VERSION,
            "timestamp_utc": now.isoformat(timespec="seconds"),
            "config_path": str(config_path),
            "config_includes": list(config_includes or []),
            "config_sha256": canonical_json_sha256(config),
            "no_cache": bool(no_cache),
            "targets": list(targets) if targets else None,
            "git_sha": self._git("rev-parse", "HEAD"),
            "git_dirty": self._git_dirty(),
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "dependencies": core_dependency_versions(packages),
            "inputs": {},
            "outputs": {},
            "stage_timings_sec": {},
            "stages": {},
        }

    def record_input(self, path, digest=None):
        """Record SHA-256 and byte size for an input file."""
        file_path = Path(path)
        if not file_path.is_file():
            return
        self.data["inputs"][str(path)] = {
            "sha256": digest or sha256_file(file_path),
            "bytes": file_path.stat().st_size,
        }

    def record_inputs(self, source_checksums):
        """Record a mapping of {path_str: sha256} into the inputs inventory."""
        for path_str, digest in (source_checksums or {}).items():
            self.record_input(path_str, digest=digest)

    def record_output(self, path, stage_name, reports_dir=None):
        """Record SHA-256, size, and emitting stage for an output file."""
        file_path = Path(path)
        if not file_path.is_file():
            return None
        label = str(file_path)
        if reports_dir is not None:
            try:
                label = file_path.resolve().relative_to(Path(reports_dir).resolve()).as_posix()
            except ValueError:
                label = str(file_path)
        self.data["outputs"][label] = {
            "sha256": sha256_file(file_path),
            "bytes": file_path.stat().st_size,
            "stage": stage_name,
        }
        return label

    def record_stage(self, name, status, elapsed_sec, phase=None, class_path=None, fingerprint=None, cache_miss_reason=None, requires=None, produces=None, input_artifacts=None, output_artifacts=None, emitted_files=None):
        """Record execution metadata and timing for a single stage."""
        elapsed = round(float(elapsed_sec), 6)
        self.data["stages"][name] = {
            "status": status,
            "phase": phase,
            "class": class_path,
            "fingerprint": fingerprint,
            "cache_miss_reason": cache_miss_reason,
            "elapsed_sec": elapsed,
            "requires": list(requires or []),
            "produces": list(produces or []),
            "input_artifacts": dict(input_artifacts or {}),
            "output_artifacts": dict(output_artifacts or {}),
            "emitted_files": list(emitted_files or []),
        }
        self.data["stage_timings_sec"][name] = elapsed

    def record_claims(self, summary):
        """Attach claim verification summary counts to the manifest."""
        self.data["claims"] = dict(summary)

    def save(self, reports_dir, timestamped_copy=False):
        """Atomically write run_manifest.json and optional timestamped copy."""
        target_dir = Path(reports_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.data, indent=2, default=str)
        primary = target_dir / "run_manifest.json"
        self._atomic_write_text(primary, payload)
        if timestamped_copy:
            copy_path = target_dir / f"run_manifest_{self.run_timestamp}.json"
            self._atomic_write_text(copy_path, payload)
        return primary

    @staticmethod
    def _atomic_write_text(path, text):
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".json", dir=path.parent)
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.replace(tmp_path, path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

    def _git(self, *args):
        try:
            result = subprocess.run(["git", *args], capture_output=True, text=True, timeout=5, check=False, cwd=self._git_cwd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        return result.stdout.strip() if result.returncode == 0 else None

    def _git_dirty(self):
        if self._git("rev-parse", "HEAD") is None:
            return None
        try:
            unstaged = subprocess.run(["git", "diff", "--quiet"], capture_output=True, timeout=5, check=False, cwd=self._git_cwd)
            staged = subprocess.run(["git", "diff", "--cached", "--quiet"], capture_output=True, timeout=5, check=False, cwd=self._git_cwd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        return unstaged.returncode == 1 or staged.returncode == 1
