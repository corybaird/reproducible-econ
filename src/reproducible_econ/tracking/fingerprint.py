import hashlib
import inspect
import json
import logging
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pandas as pd

from reproducible_econ.config import get_nested

logger = logging.getLogger(__name__)

CORE_PACKAGES = ("pandas", "pyarrow", "pyyaml", "reproducible-econ")
_CHUNK_SIZE = 1024 * 1024

def sha256_file(path, chunk_size=_CHUNK_SIZE):
    """Compute a streaming SHA-256 hex digest for a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_sha256(value):
    """Compute a deterministic SHA-256 hex digest over canonical JSON."""
    encoded = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def core_dependency_versions(packages=CORE_PACKAGES):
    """Return installed versions for declared public core packages."""
    versions = {}
    for package in packages:
        try:
            versions[package] = version(package)
        except PackageNotFoundError:
            versions[package] = None
    return versions


@dataclass
class FingerprintResult:
    """Computed stage fingerprint along with per-component hashes and source files."""

    fingerprint: str
    components: dict
    sources: dict


class CacheFingerprint:
    """Compute v2 stage fingerprints and per-component sub-hashes."""

    FORMAT_VERSION = "2"

    def compute(self, stage, config, cache_inputs, data, upstream_keys, include_output_config=False, extra_packages=None, allow_non_dataframe_upstream=False):
        """Compute a FingerprintResult from config, sources, upstream frames, code, and deps."""
        selected_config = self._select_config(config, cache_inputs, include_output_config=include_output_config)
        sources = self._source_checksums(selected_config)
        upstream = self._upstream_checksums(data, upstream_keys, allow_non_dataframe=allow_non_dataframe_upstream)
        packages = tuple(dict.fromkeys([*CORE_PACKAGES, *(extra_packages or ())]))
        payload = {
            "format_version": self.FORMAT_VERSION,
            "config": selected_config,
            "sources": sources,
            "upstream": upstream,
            "stage_source": self._stage_source(stage),
            "dependencies": core_dependency_versions(packages),
        }
        fingerprint = canonical_json_sha256(payload)[:16]
        components = {key: canonical_json_sha256(val)[:16] for key, val in payload.items()}
        return FingerprintResult(fingerprint=fingerprint, components=components, sources=sources)

    @staticmethod
    def _select_config(config, cache_inputs, include_output_config=False):
        if cache_inputs:
            return {key: get_nested(config, key, default=None) for key in cache_inputs}
        excluded = ("cache",) if include_output_config else ("output", "cache")
        return {key: val for key, val in config.items() if key not in excluded}

    _OUTPUT_CONFIG_KEYS = frozenset({"output", "output_path", "macros_path", "claims_path", "tables_dir", "figures_dir", "reports_dir", "cache_dir"})
    @classmethod
    def _source_checksums(cls, value):
        checksums = {}
        if isinstance(value, dict):
            for key, item in value.items():
                if key in cls._OUTPUT_CONFIG_KEYS:
                    continue
                checksums.update(cls._source_checksums(item))
        elif isinstance(value, (list, tuple)):
            for item in value:
                checksums.update(cls._source_checksums(item))
        elif isinstance(value, str) and value:
            try:
                path = Path(value)
                is_file = path.is_file()
            except OSError:
                is_file = False
            if is_file:
                checksums[value] = sha256_file(path)
        return checksums

    @staticmethod
    def _upstream_checksums(data, upstream_keys, allow_non_dataframe=False):
        from reproducible_econ.tracking.metadata import CacheArtifactMetadata

        upstream = {}
        for key in upstream_keys or ():
            if key in data:
                value = data[key]
                if isinstance(value, pd.DataFrame):
                    upstream[key] = CacheArtifactMetadata.frame_sha256(value)
                elif allow_non_dataframe:
                    upstream[key] = canonical_json_sha256(value)
                else:
                    raise TypeError(f"Upstream cache artifact {key!r} must be a pandas DataFrame")
        return upstream

    @staticmethod
    def _stage_source(stage):
        try:
            return inspect.getsource(stage.__class__)
        except (OSError, TypeError):
            cls = stage.__class__
            qual = f"{cls.__module__}.{cls.__qualname__}"
            logger.warning("Could not inspect source for %s; falling back to qualified class name", qual)
            return qual


