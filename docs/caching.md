# Caching

Caching lives in `reproducible_econ/tracking/`: `CacheFingerprint` (`fingerprint.py`), `CacheArtifactMetadata` (`metadata.py`), and `StageCache` (`cache.py`).

## Fingerprints

A cached stage (`cache: true`) gets a v2 fingerprint: a deterministic SHA-256 over canonical JSON containing

- `config`: the config keys listed in `cache_inputs` (or the whole config minus `output`/`cache` when omitted)
- `sources`: SHA-256 of any source file paths mentioned in the selected config
- `upstream`: content hashes of required upstream DataFrames
- `stage_source`: the stage class's inspected source code
- `dependencies`: versions of `pandas`, `pyarrow`, `pyyaml`, `reproducible-econ` (plus `matplotlib` for figure stages)

The fingerprint is truncated to 16 hex characters. Per-component sub-hashes (`FingerprintResult.components`) power the miss diagnostics below.

## What Invalidates a Stage

A stored fingerprint no longer matching means re-execution. Causes:

- A `cache_inputs` config value changed
- The stage class's source code changed
- An upstream DataFrame's content or schema changed
- A source file referenced in the config changed
- A dependency version changed

`--no-cache` forces re-execution of every cached stage (`cache_miss_reason: "no_cache_flag"`) without touching stored entries.

## Invalidation Reasons

`cache_miss_reason` values recorded in the manifest:

- `no_cache` — no stored cache entry
- `no_cache_flag` — run invoked with `--no-cache`
- `fingerprint_changed: <changed components>` — fingerprint mismatch with a prior entry on disk
- `missing_metadata`, `missing_artifact` — incomplete cache entry
- `checksum_mismatch`, `metadata_mismatch` — stored parquet failed validation before load

## Metadata Sidecars

Per stage and fingerprint (`<cache_dir>/<stage>/<fingerprint>/`):

- `<key>.parquet` — one file per declared output key
- `metadata.json` — `format_version` plus per-artifact `rows`, `columns`, `dtypes`, `index_names`, `frame_sha256` (content + schema hash), and `file_sha256`
- `fingerprint_summary.json` — the per-component hashes for miss diagnostics

On load, the parquet file's SHA-256 and the reloaded frame's metadata are both verified before the cache is trusted. Writes are atomic (temp dir + `os.replace`), and prior fingerprint directories are pruned to `cache.retain_prior_fingerprints` (default 2).

## Up-to-Date Skip for Emitters

Non-cached emitter stages (tables, macros, figures, claims) do not store parquet. Instead, `StageCache` writes an `emitter_stamp.json` per stage containing the stage fingerprint, component hashes, and SHA-256 hashes of every emitted file.

On the next run with identical upstream inputs:

- If the stamp fingerprint matches and all emitted files are unchanged, the stage is skipped as `up_to_date` and its recorded outputs are re-listed in the manifest.
- If any emitted file was edited or deleted (`output_modified`, `missing_output`), the stage re-executes and regenerates all of its files.

## Run Manifest

`RunManifest` (`manifest.py`) writes `run_manifest.json` (plus a `run_manifest_<timestamp>.json` copy when `output.timestamped_manifest: true`) under `reports_dir`:

- Run level: `manifest_version`, `timestamp_utc`, `config_path`, `config_includes`, `config_sha256`, `no_cache`, `targets`, `git_sha`, `git_dirty`, `python_version`, `platform`, `dependencies`
- `inputs`: SHA-256 and byte size of every referenced source file
- `outputs`: SHA-256, size, and emitting stage per report file (labels relative to `reports_dir`)
- `stages` / `stage_timings_sec`: per stage `status` (`executed`, `cache_hit`, `up_to_date`, `skipped`), `phase`, `class`, `fingerprint`, `cache_miss_reason`, `elapsed_sec`, `requires`, `produces`, input/output artifact summaries, and `emitted_files`
- `claims`: passed/failed/unresolved counts from `ClaimCheckStage` when the pipeline runs one
