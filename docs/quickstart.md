# Quickstart

The fastest path from clone to a working, cached pipeline run with LaTeX report output.

## 1. Install

From the repository root (requires [uv](https://docs.astral.sh/uv/)):

```bash
git clone https://github.com/corybaird/reproducible-econ && cd reproducible-econ
uv sync
uv sync --extra figures   # optional matplotlib figure support
```

Core dependencies are `pandas`, `pyarrow`, and `pyyaml`; figures are an optional extra.

## 2. Run the Example Pipeline

```bash
uv run --extra figures python -m reproducible_econ.pipeline.runner \
  --config references/configs/example_pipeline.yaml
```

This runs the synthetic Phillips curve pipeline: it generates its data deterministically from a seed (no external CSVs or network calls), estimates two OLS specs, and emits reports.

## 3. What You Get

Everything lands under the project root, in directories set by the config's `output:` block:

- `reports/macro_demo/tables/summary_stats.tex`, `tables/phillips_estimates.tex` — booktabs LaTeX tables
- `reports/macro_demo/figures/phillips_scatter.png` — figure (with `--extra figures`)
- `reports/macro_demo/macros.tex` — `\newcommand` macros like `\BaselineCoef`
- `reports/macro_demo/claims_report.json` — claim check results
- `reports/macro_demo/run_manifest.json` — full provenance manifest
- `.cache/macro_demo/` — parquet cache with fingerprints

## 4. Cache on Rerun

Run the same command a second time: cached stages (`prepare_data`, `estimate_ols`) report `cache_hit` and reload verified parquet artifacts; emitters are skipped as `up_to_date` since their output files are unchanged. Change a `cache_inputs` value (e.g. `estimation.winsorize_pct`) and only affected stages re-execute.

## 5. Use It from Python

```python
from reproducible_econ import PipelineRunner

runner = PipelineRunner(config_path="references/configs/example_pipeline.yaml")
data = runner.run()
print(runner.manifest_path, runner.last_manifest["stages"].keys())
```

Or run pre-built stages directly — see the `Direct StageExecutor Usage` section of the [README](../README.md).

## Next Steps

- [architecture.md](architecture.md) — package layout and execution flow
- [configuration.md](configuration.md) — YAML schema, includes, interpolation, stage fields
- [caching.md](caching.md) — fingerprints, invalidation reasons, manifest contents
- [emitters.md](emitters.md) — tables, macros, figures, claim checks
- [projects.md](projects.md) — the two applied research pipelines
