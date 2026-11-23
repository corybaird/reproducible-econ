# Projects

Applied pipelines live under `projects/`. They are driven by the same `PipelineRunner` and YAML config format; the difference is that stages import econometric models from [stats-transformer](https://github.com/corybaird/stats-transformer) (`--with` supplies it without adding it to `pyproject.toml`).

## Nakamura and Steinsson (2018) — Basic

`projects/nakamura_steinsson_2018/`: single-model replication of QJE Table I (`RobustOLSModel` HC1 OLS across 2Y–10Y nominal, real, and breakeven yields), with booktabs tables, paper macros, and five declarative `ClaimCheckStage` claims against published values.

```bash
uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/nakamura_steinsson_2018/pipeline.yaml
```

## Bauer and Swanson (2023) — Advanced

`projects/bauer_swanson_2023/`: multi-model FRBSF monetary-policy-surprises pipeline — Eurodollar PCA alignment, payroll-news predictability OLS, Jordà local projections (orthogonalized vs raw shocks plus 12-lag robustness), Proxy-SVAR, and LP-IV — with tables, IRF figures, macros, and seven claim checks.

```bash
uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/bauer_swanson_2023/pipeline.yaml
```

## Gertler and Karadi (2015) — MATLAB-checked

`projects/gertler_karadi_2015/`: four-variable proxy-SVAR instrumented with high-frequency fed funds futures surprises, with an IRF table, figure, macros, and claim checks against a recorded MATLAB VAR-Toolbox run.

```bash
uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/gertler_karadi_2015/pipeline.yaml
```

## Required Data

Raw data under `data/raw/<project>/` is gitignored; download and standardize it before running. File lists and sources are in each project's README:

- `projects/nakamura_steinsson_2018/README.md` — four parquet files (nominal yields, real yields, FOMC meetings, policy news shocks)
- `projects/bauer_swanson_2023/README.md` — two parquet files (FOMC event-study and monthly FRBSF series)
- `projects/gertler_karadi_2015/README.md` — the AEJ replication workbook `GK2015_Data.xlsx`

Outputs go to `reports/<project>/` and cached artifacts to `.cache/<project>/`.

## Overleaf Workflow

There is no Overleaf sync code. To feed a paper:

1. Clone your Overleaf project locally.
2. Point `output.reports_dir` (and derived `tables_dir`, `figures_dir`, `macros_path`, `claims_path`) at a subfolder inside that checkout, e.g. `reports/paper_name`.
3. Optionally set `output.timestamped_manifest: true` to archive a timestamped manifest copy per run.
4. Review `git diff` in the clone and push with your own workflow.

## Writing Your Own Project

1. Create `projects/<name>/` with two files:
   - `pipeline.yaml` — config plus stage declarations; set `default_module: projects.<name>.stages`
   - `stages.py` — stage classes subclassing `reproducible_econ.pipeline.stage.BaseStage` (or the `reproducible_econ.emitters` stages) implementing `run(self, data, config)`
2. Importability comes from the repo root joining `sys.path`: `PipelineRunner` adds the project root (the nearest ancestor of the config containing `pyproject.toml`) to `sys.path` before importing stage modules, so `projects.<name>.stages` resolves via namespace packages without an `__init__.py`.
3. Put raw inputs under `data/raw/<name>/` and reference them with `${project_root}` (e.g. `data: {raw_path: ${project_root}/data/raw/<name>/file.parquet}`).
4. Declare stages with `requires` / `produces` artifact keys, set `cache: true` on expensive computation stages, and use the emitter stages for tables, macros, figures, and claims. See [configuration.md](configuration.md) for stage fields and [emitters.md](emitters.md) for their config blocks.
5. Run:

```bash
uv run --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/<name>/pipeline.yaml
```
