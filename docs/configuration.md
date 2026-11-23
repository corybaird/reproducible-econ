# Configuration

Pipelines are declared in YAML and loaded by `ConfigLoader` (`src/reproducible_econ/config.py`).

## Run a Config

```bash
python -m reproducible_econ.pipeline.runner --config <path/to/pipeline.yaml>
```

## Schema and Example

Excerpt from `references/configs/example_pipeline.yaml`:

```yaml
includes: []

project:
  name: macro_demo
  seed: 42

data:
  economies: [ECON_A, ECON_B, ECON_C, ECON_D]
  n_quarters: 30
  start_year: 2015
  start_quarter: "2015Q1"
  end_quarter: "2022Q2"
  lag_periods: 1
  dgp:
    intercept: 2.0
    slope_unemp: -0.45
    persistence: 0.55
    noise_std: 0.25

estimation:
  winsorize_pct: 0.0
  specs:
    - name: baseline_ols
      dependent: inflation
      regressors: [unemployment_gap, lag_inflation]

output:
  cache_dir: .cache/macro_demo
  reports_dir: reports/macro_demo
  tables_dir: ${output.reports_dir}/tables
  figures_dir: ${output.reports_dir}/figures
  macros_path: ${output.reports_dir}/macros.tex
  claims_path: ${output.reports_dir}/claims_report.json
  timestamped_manifest: false

cache:
  retain_prior_fingerprints: 2

plotting:
  enabled: true
  dpi: 200
  on_missing_matplotlib: skip

tables:          # consumed by LatexTableStage
  strict: true
  exports:
    - key: estimates
      filename: phillips_estimates.tex
      caption: "Synthetic Phillips Curve OLS Estimates"
      label: "tab:phillips_estimates"
      float_format: "%.4f"
      columns: [spec_name, key_variable, coef, se, pval, n_obs, r2]

latex_macros:    # consumed by LatexMacroStage
  output_path: ${output.macros_path}
  precision: 4
  fields: [coef, se, pval, n_obs]
  entries:
    - tidy_key: estimates
      spec: baseline_ols
      key_variable: unemployment_gap
      name: Baseline

claims:          # consumed by ClaimCheckStage
  fail_on_error: false
  entries:
    - id: phillips_slope_negative
      description: "Baseline unemployment gap slope is negative and statistically significant"
      tidy_key: estimates
      spec: baseline_ols
      key_variable: unemployment_gap
      sign: negative
      pval_below: 0.05

default_module: reproducible_econ.examples.macro_demo

stages:
  - name: prepare_data
    class: PrepareMacroDataStage
    phase: data
    produces: [panel, summary_stats]
    cache: true
    cache_inputs: [data, project]

  - name: estimate_ols
    module: reproducible_econ.examples.macro_demo
    class: EstimatePhillipsStage
    phase: estimate
    requires: [panel]
    produces: [estimates]
    cache: true
    cache_inputs: [estimation]

  - name: export_tables
    module: reproducible_econ.emitters.tables
    class: LatexTableStage
    phase: report
    requires: [summary_stats, estimates]
    cache: false
```

Top-level keys other than the reserved ones (`stages`, `default_module`, `includes`, `output`, `cache`) are free-form project configuration read by your stages via `config`.

## Includes

- `includes` is a list of YAML paths, resolved relative to the including file's directory.
- Includes are merged recursively; duplicate top-level keys raise `ValueError`, as do circular include chains.

## `${var}` Interpolation

- `${dotted.key}` is replaced by the value at that path in the merged config; `${output.reports_dir}/figures` concatenates into a string.
- A string that is exactly one token (`${output.reports_dir}`) resolves to the referenced value as-is (not stringified).
- Built-in variables: `${project_root}` (nearest ancestor of the config containing `pyproject.toml`), `${config_dir}` (config file's directory), `${run_timestamp}` (UTC `%Y%m%dT%H%M%SZ`).
- Undefined tokens and circular references raise `ValueError`.

## Stage Fields

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | Unique stage identifier used in `--targets` and the manifest |
| `class` / `class_path` | yes | Class name (resolved via `module` or `default_module`) or fully qualified `module.ClassName` |
| `module` | no | Module the class is imported from; defaults to top-level `default_module` |
| `phase` | no | Logical group (e.g. `data`, `estimate`, `report`); usable as a `--targets` value |
| `order` | no | Integer tie-breaker for topological sort (default: declaration order) |
| `requires` | no | Artifact keys consumed; each must be produced earlier or passed as initial data |
| `produces` | no | Artifact keys the stage adds to the shared data dict |
| `cache` | no | If `true`, declared outputs are cached as parquet and reloaded on fingerprint match |
| `cache_inputs` | no | Config keys fingerprinted for this stage; default hashes the full config (minus `output`/`cache`) |
| `cache_outputs` | no | Data keys persisted to cache; defaults to `produces` |
| `init_args` | no | Keyword arguments passed to the stage class constructor |
| `enabled_config` | no | Dotted config key; stage is skipped (and recorded as `skipped`) when falsy |

`StageGraph` raises `ValueError` on duplicate stage names, duplicate artifact producers, missing producers, and dependency cycles. An enabled stage cannot require an artifact from a disabled stage.

## Path Resolution

- The project root is the nearest ancestor of the config file containing `pyproject.toml` (`resolve_project_root`).
- Relative `output.*_dir`/`output.*_path` values and `latex_macros.output_path` are made absolute against that root after interpolation, so runs are independent of the working directory.
- Non-output strings (e.g. `data.fomc_path` in `projects/bauer_swanson_2023/pipeline.yaml`) stay as written; use `${project_root}` explicitly for repo-relative input files.
