import logging
import time
from pathlib import Path

import pandas as pd

from reproducible_econ.config import resolve_project_root
from reproducible_econ.tracking.cache import StageCache
from reproducible_econ.tracking.fingerprint import CacheFingerprint
from reproducible_econ.tracking.manifest import RunManifest, summarize_artifact

logger = logging.getLogger(__name__)

EMITTED_FILES_KEY = "_reproducible_econ_emitted_files"
CLAIMS_SUMMARY_KEY = "_reproducible_econ_claims_summary"


def _resolve_path(raw_path, project_root):
    path = Path(raw_path)
    return path if path.is_absolute() else (project_root / path).resolve()


class StageExecutor:
    """Execute pipeline stages with atomic parquet caching and provenance manifests."""

    def __init__(self, config, config_path, no_cache=False, config_includes=None, targets=None, run_timestamp=None):
        self.config = config
        self.config_path = str(config_path)
        self.no_cache = bool(no_cache)
        self.project_root = resolve_project_root(config_path)
        output = config.get("output") or {}
        cache_cfg = config.get("cache") or {}
        self.cache_dir = _resolve_path(output.get("cache_dir", ".cache/reproducible_econ"), self.project_root)
        self.reports_dir = _resolve_path(output.get("reports_dir", "reports"), self.project_root)
        self.timestamped_manifest = bool(output.get("timestamped_manifest", False))
        retain = cache_cfg.get("retain_prior_fingerprints", 2)
        self.cache = StageCache(self.cache_dir, retain_prior_fingerprints=retain)
        self.fingerprinter = CacheFingerprint()
        self._manifest = RunManifest(
            config,
            config_path,
            no_cache=self.no_cache,
            config_includes=config_includes,
            targets=targets,
            run_timestamp=run_timestamp,
        )
        self.manifest = self._manifest.data

    def run(self, name, stage, data, cache_inputs=None, cache=False, output_keys=None, upstream_keys=None, phase=None, produces=None):
        """Execute a stage or load its declared DataFrame outputs from cache."""
        output_keys = list(output_keys or ())
        upstream_keys = list(upstream_keys or ())
        produces = list(produces) if produces is not None else list(output_keys)
        class_path = f"{stage.__class__.__module__}.{stage.__class__.__qualname__}"
        use_cache = bool(cache) and not self.no_cache
        if use_cache and not output_keys:
            raise ValueError("Cached stages must declare output_keys")

        input_artifacts = {key: summarize_artifact(data[key]) for key in upstream_keys if key in data}
        fp_result = None
        emitter_fp = None
        miss_reason = None
        if cache:
            fp_result = self.fingerprinter.compute(stage, self.config, cache_inputs, data, upstream_keys)
            self._manifest.record_inputs(fp_result.sources)
        else:
            emitter_fp = self.fingerprinter.compute(
                stage,
                self.config,
                cache_inputs,
                data,
                upstream_keys,
                include_output_config=True,
                extra_packages=("matplotlib",),
                allow_non_dataframe_upstream=True,
            )

        if use_cache:
            hit, miss_reason = self.cache.load(name, fp_result.fingerprint, data, output_keys, component_hashes=fp_result.components)
            if hit:
                logger.info("Stage %s: cache hit (%s)", name, fp_result.fingerprint)
                output_artifacts = {key: summarize_artifact(data[key]) for key in produces if key in data}
                self._manifest.record_stage(
                    name,
                    status="cache_hit",
                    elapsed_sec=0.0,
                    phase=phase,
                    class_path=class_path,
                    fingerprint=fp_result.fingerprint,
                    cache_miss_reason=None,
                    requires=upstream_keys,
                    produces=produces,
                    input_artifacts=input_artifacts,
                    output_artifacts=output_artifacts,
                    emitted_files=[],
                )
                return data
            logger.info("Stage %s: cache miss (%s)", name, miss_reason)
        elif cache and self.no_cache:
            miss_reason = "no_cache_flag"
            logger.info("Stage %s: executing (%s)", name, miss_reason)
        elif not self.no_cache:
            up_to_date, stamp, miss_reason = self.cache.load_emitter_stamp(name, emitter_fp.fingerprint, component_hashes=emitter_fp.components)
            if up_to_date:
                emitted_labels = []
                for emitted_path in stamp["emitted_files"]:
                    label = self._manifest.record_output(emitted_path, name, reports_dir=self.reports_dir)
                    if label is not None:
                        emitted_labels.append(label)
                if stamp.get("claims_summary") is not None:
                    self._manifest.record_claims(stamp["claims_summary"])
                logger.info("Stage %s: up to date (%s)", name, emitter_fp.fingerprint)
                self._manifest.record_stage(
                    name,
                    status="up_to_date",
                    elapsed_sec=0.0,
                    phase=phase,
                    class_path=class_path,
                    fingerprint=emitter_fp.fingerprint,
                    cache_miss_reason=None,
                    requires=upstream_keys,
                    produces=produces,
                    input_artifacts=input_artifacts,
                    output_artifacts={},
                    emitted_files=emitted_labels,
                )
                return data
            if miss_reason and miss_reason != "no_cache":
                logger.info("Stage %s: executing (%s)", name, miss_reason)
            else:
                logger.info("Stage %s: executing", name)
        else:
            miss_reason = "no_cache_flag"
            logger.info("Stage %s: executing (%s)", name, miss_reason)

        data[EMITTED_FILES_KEY] = []
        started = time.perf_counter()
        try:
            data = stage.run(data, self.config)
        finally:
            emitted_paths = data.pop(EMITTED_FILES_KEY, [])
            claims_summary = data.pop(CLAIMS_SUMMARY_KEY, None)

        for key in output_keys:
            if key not in data or not isinstance(data[key], pd.DataFrame):
                raise TypeError(f"Stage {name} must return DataFrame artifact {key}")
        elapsed = time.perf_counter() - started

        if use_cache:
            self.cache.save(name, fp_result.fingerprint, data, output_keys, component_hashes=fp_result.components)
        elif not cache and not self.no_cache and emitted_paths:
            self.cache.save_emitter_stamp(
                name,
                emitter_fp.fingerprint,
                emitted_paths,
                component_hashes=emitter_fp.components,
                claims_summary=claims_summary,
            )

        emitted_labels = []
        for emitted_path in emitted_paths:
            label = self._manifest.record_output(emitted_path, name, reports_dir=self.reports_dir)
            if label is not None:
                emitted_labels.append(label)
        if claims_summary is not None:
            self._manifest.record_claims(claims_summary)

        recorded_fp = fp_result.fingerprint if fp_result is not None else (emitter_fp.fingerprint if emitted_paths else None)
        recorded_miss = miss_reason if (cache or emitted_paths) else None
        output_artifacts = {key: summarize_artifact(data[key]) for key in produces if key in data}
        self._manifest.record_stage(
            name,
            status="executed",
            elapsed_sec=elapsed,
            phase=phase,
            class_path=class_path,
            fingerprint=recorded_fp,
            cache_miss_reason=recorded_miss,
            requires=upstream_keys,
            produces=produces,
            input_artifacts=input_artifacts,
            output_artifacts=output_artifacts,
            emitted_files=emitted_labels,
        )
        return data

    def record_skipped(self, name, phase=None, class_path=None, requires=None, produces=None):
        """Record a disabled stage in the manifest without executing it."""
        logger.info("Stage %s: skipped (disabled by config)", name)
        self._manifest.record_stage(
            name,
            status="skipped",
            elapsed_sec=0.0,
            phase=phase,
            class_path=class_path,
            fingerprint=None,
            cache_miss_reason=None,
            requires=requires,
            produces=produces,
            input_artifacts={},
            output_artifacts={},
            emitted_files=[],
        )

    def finalize(self):
        """Atomically persist the run manifest under reports_dir."""
        return self._manifest.save(self.reports_dir, timestamped_copy=self.timestamped_manifest)
