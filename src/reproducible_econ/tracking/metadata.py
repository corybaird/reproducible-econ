import hashlib
import json

import pandas as pd

from reproducible_econ.tracking.fingerprint import sha256_file


class CacheArtifactMetadata:
    """Build and validate structural and file-level metadata for cached DataFrames."""

    FORMAT_VERSION = "2"

    @classmethod
    def frame_sha256(cls, frame):
        """Compute a content and schema SHA-256 digest for a pandas DataFrame."""
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Cache artifacts must be pandas DataFrames")
        digest = hashlib.sha256()
        schema = {
            "columns": [str(col) for col in frame.columns],
            "dtypes": [str(dtype) for dtype in frame.dtypes],
            "index_names": list(frame.index.names),
        }
        digest.update(json.dumps(schema, sort_keys=True, default=str).encode("utf-8"))
        digest.update(pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes())
        return digest.hexdigest()

    @classmethod
    def build(cls, frame, file_path=None):
        """Build a metadata dictionary describing a DataFrame and optional parquet file."""
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("Cache artifacts must be pandas DataFrames")
        entry = {
            "rows": len(frame),
            "columns": [str(col) for col in frame.columns],
            "dtypes": {str(col): str(dtype) for col, dtype in zip(frame.columns, frame.dtypes, strict=True)},
            "index_names": list(frame.index.names),
            "frame_sha256": cls.frame_sha256(frame),
        }
        if file_path is not None:
            entry["file_sha256"] = sha256_file(file_path)
        return entry

    @classmethod
    def validate_file_checksum(cls, file_path, expected):
        """Return True if file_path matches the expected file_sha256."""
        expected_hash = expected.get("file_sha256")
        if not expected_hash:
            return False
        return sha256_file(file_path) == expected_hash

    @classmethod
    def validate(cls, frame, expected, file_path=None):
        """Validate a DataFrame (and optional parquet file) against expected metadata."""
        if file_path is not None and not cls.validate_file_checksum(file_path, expected):
            return False, "checksum_mismatch"
        actual = cls.build(frame)
        for field in ("rows", "columns", "dtypes", "index_names", "frame_sha256"):
            if actual.get(field) != expected.get(field):
                return False, "metadata_mismatch"
        return True, None


