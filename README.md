# Reproducible Econ

Config-driven stage execution, atomic parquet DataFrame caching, provenance manifests, and paper-ready report emitters for reproducible economic research.

## Status

- Version `0.1.0`, first public release (beta): APIs and configs may change before 1.0
- Release notes: [CHANGELOG.md](CHANGELOG.md), plans: [ROADMAP.md](ROADMAP.md)

## What This Repo Does

`reproducible-econ` is the lightweight pipeline infrastructure layer for the [Econ Agent Harness workshop](https://github.com/corybaird/econ-agent-workshop):

- **One-command pipeline runner:** Load a single YAML config (`includes:` + `${var}` interpolation), validate the stage DAG (cycle and missing-producer checks), and execute stages in topological order via `uv run python -m reproducible_econ.pipeline.runner --config <yaml>`.
- **Atomic stage cache with v2 fingerprints:** Cache declared pandas DataFrame outputs as parquet with metadata sidecars, SHA-256 verification before load, retention pruning, and explicit `cache_miss_reason` diagnostics (`no_cache`, `no_cache_flag`, `fingerprint_changed: <components>`, `checksum_mismatch`, `metadata_mismatch`).
- **Run manifest (`run_manifest.json`):** Record Git commit and dirty state (staged + unstaged), Python and public package versions, config SHA-256, input/output file inventories, per-stage timings/fingerprints/artifact summaries, and claim verification counts.
- **Report emitters:** Emit booktabs LaTeX tables (`LatexTableStage`), `\newcommand` paper macros (`LatexMacroStage`), optional matplotlib figures (`FigureStageBase`), and declarative econometric claim checks (`ClaimCheckStage`).

It intentionally contains no LLM, transformer, cloud, Overleaf API, or agent dependencies.

## Install for Development

Core runtime dependencies are `pandas`, `pyarrow`, and `pyyaml`. Figure generation uses an optional `figures` extra (`matplotlib>=3.8`).

```bash
uv sync
uv run pytest -q
```

To include optional matplotlib figure generation:

```bash
uv sync --extra figures
uv run --extra figures pytest -q
```

Not yet on PyPI, install from GitHub:

```bash
uv add "reproducible-econ @ git+https://github.com/corybaird/reproducible-econ"
```

## Quickstart

```bash
uv run --extra figures python -m reproducible_econ.pipeline.runner \
  --config references/configs/example_pipeline.yaml
```

Runs the synthetic Phillips curve pipeline end to end: LaTeX tables, macros, a figure, claim checks, and a provenance manifest under `reports/macro_demo/`, with a parquet cache under `.cache/macro_demo/`. See [docs/quickstart.md](docs/quickstart.md) and the package tour below.

## Quickstart: Synthetic Phillips Curve Example

The repository ships a self-contained synthetic Phillips curve pipeline (`src/reproducible_econ/examples/macro_demo.py`, driven by `references/configs/example_pipeline.yaml`) that generates its quarterly panel deterministically from `project.seed` with no external CSV or network calls.

### 1. Cold Run

```bash
uv run --extra figures python -m reproducible_econ.pipeline.runner \
  --config references/configs/example_pipeline.yaml
```

Without `--extra figures`, `plot_phillips` skips cleanly with a warning (`plotting.on_missing_matplotlib: skip`) and all other stages complete normally.

Outputs land under `reports/macro_demo/`:

- `tables/summary_stats.tex` — booktabs summary statistics table
- `tables/phillips_estimates.tex` — booktabs OLS regression results table
- `figures/phillips_scatter.png` — scatter plot + fitted line (when `--extra figures` is installed)
- `macros.tex` — `\newcommand` macros (`\BaselineCoef`, `\BaselineCoefShort`, `\BaselineSE`, `\BaselineP`, `\BaselineN`, `\PersistenceCoef`, `\UnivariateCoef`, ...)
- `claims_report.json` — declarative verification for headline slope and persistence claims (`fail_on_error: false` by default; warnings logged and counts recorded in the manifest)
- `run_manifest.json` — full provenance manifest

### 2. Warm Cache Hit

Run the exact same command a second time:

```bash
uv run --extra figures python -m reproducible_econ.pipeline.runner \
  --config references/configs/example_pipeline.yaml
```

`prepare_data` and `estimate_ols` both report `cache_hit` (`elapsed_sec: 0.0`) and reload their verified parquet artifacts from `.cache/macro_demo/`.

### 3. One-Line Config Diff

Change a single parameter in `references/configs/example_pipeline.yaml` — for example, set `estimation.winsorize_pct: 0.05` (or change `data.lag_periods` / `data.end_quarter`) — and re-run:

- Editing `estimation.winsorize_pct`: `prepare_data` hits cache (`status: "cache_hit"`), while `estimate_ols` re-executes with `cache_miss_reason: "fingerprint_changed: config"` and refreshes `phillips_estimates.tex`, `macros.tex`, `phillips_scatter.png`, `claims_report.json`, and `run_manifest.json`.
- Editing `data.end_quarter` or `data.lag_periods`: `prepare_data` re-executes with `cache_miss_reason: "fingerprint_changed: config"`, and `estimate_ols` re-executes with `cache_miss_reason: "fingerprint_changed: upstream"`.

### 4. Targeted Runs and Forced Re-Execution

Run a subset of stages or a phase (automatically pulling in required upstream stages):

```bash
uv run python -m reproducible_econ.pipeline.runner \
  --config references/configs/example_pipeline.yaml \
  --targets export_macros check_claims
```

Bypass the cache for all stages:

```bash
uv run python -m reproducible_econ.pipeline.runner \
  --config references/configs/example_pipeline.yaml \
  --no-cache
```

## Applied Research Projects

Two real-data applied pipelines live under `projects/` (data under `data/raw/` is gitignored and not committed):

- **Basic (single model):** [Nakamura and Steinsson (2018) yield-curve event study](projects/nakamura_steinsson_2018/README.md) — `RobustOLSModel` replication of QJE Table I with LaTeX tables, paper macros, and declarative `ClaimCheckStage` verification (`projects/nakamura_steinsson_2018/pipeline.yaml`).
- **Advanced (multi-model):** [Bauer and Swanson (2023) monetary policy surprises](projects/bauer_swanson_2023/README.md) — FOMC Eurodollar PCA alignment, pre-announcement predictability OLS, Jordà local projections (`mps_orth` vs raw `mps` and 12-lag robustness), Proxy-SVAR, LP-IV, IRF figures, tables, macros, and claim checks (`projects/bauer_swanson_2023/pipeline.yaml`).

Citations for the papers and datasets these projects use are in [docs/citations.md](docs/citations.md) and [docs/data_sources.md](docs/data_sources.md).

Run either project with `stats-transformer` via `uv run --with`:

```bash
uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/nakamura_steinsson_2018/pipeline.yaml

uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/bauer_swanson_2023/pipeline.yaml
```

## Report Emitters and Overleaf Workflow

`reproducible-econ` contains **no Overleaf sync, git-push, or API code**. All report artifacts write under a single configurable `output.reports_dir` with stable filenames (`tables/*.tex`, `figures/*.png`, `macros.tex`, `claims_report.json`, `run_manifest.json`) so paper `\input{}` and `\includegraphics{}` references do not break across runs.

To use with Overleaf:

1. Clone your Overleaf project locally.
2. Point `output.reports_dir` in your YAML config at a subfolder inside that checkout (or copy the directory in your own build script).
3. Review the git diff and commit/push with your own git workflow.

If you also want a timestamped archive of each manifest alongside `run_manifest.json`, set `output.timestamped_manifest: true` (or use `${run_timestamp}` inside `output.reports_dir`).

### Included Emitters

- `reproducible_econ.emitters.LatexTableStage`: Pure-Python `booktabs` LaTeX table exporter (zero `jinja2` dependency) with automatic LaTeX escaping, column subsetting/renaming, and optional `.csv` mirror.
- `reproducible_econ.emitters.LatexMacroStage`: Emits `\newcommand` macros from tidy DataFrames with strict checks for missing, ambiguous, NaN, or colliding macro names.
- `reproducible_econ.emitters.FigureStageBase`: Base stage for `matplotlib` figures with lazy import, headless `"Agg"` backend setup, optional `.mplstyle`, and configurable `skip`/`error` behavior when the `figures` extra is absent.
- `reproducible_econ.emitters.ClaimCheckStage`: Verifies declarative claims (`sign`, `coef` ± `tol`, `pval_below`/`pval_above`/`pval_between`, `n_obs`, `date_min`/`date_max`, and generic `bounds`), writes `claims_report.json`, and records counts in `run_manifest.json["claims"]`.

## Direct `StageExecutor` Usage

Stages can also be executed directly without the YAML runner. A stage implements `run(data, config)` and stores DataFrame outputs in `data`:

```python
from reproducible_econ import StageExecutor

config = {
    "factor": 2,
    "output": {"cache_dir": ".cache/example", "reports_dir": "reports/example"},
}

executor = StageExecutor(config, "params.yaml")
data = executor.run(
    "estimate",
    EstimateStage(),
    data,
    cache_inputs=["factor"],
    cache=True,
    output_keys=["estimates"],
    upstream_keys=["model_data"],
)
manifest_path = executor.finalize()
```

When `cache_inputs` is omitted on a cached stage, `StageExecutor` hashes the full config excluding the `output` and `cache` blocks so report directory changes do not bust computation caches.

## Workshop Integration

The harness combines this package with:

- [stats-transformer](https://github.com/corybaird/stats-transformer)
- [auto-econ-sentiment](https://github.com/corybaird/auto-econ-sentiment)
- [econ-pdf-extract](https://github.com/corybaird/econ-pdf-extract)

Runnable workshop notebooks and configs: [econ-agent-workshop](https://github.com/corybaird/econ-agent-workshop).

## Scope

- Deterministic config-driven stage execution
- Explicit DataFrame artifacts with atomic parquet caching
- Content-based v2 cache fingerprints and miss diagnostics
- Provenance manifests and paper-ready report emitters

The package does not provide econometric model suites, LLM/agent tooling, Overleaf sync clients, distributed execution, or a workflow GUI.

## License

MIT
