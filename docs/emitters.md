# Emitters

Emitters are non-cached stages in `reproducible_econ/emitters/` that write report artifacts under `output.reports_dir` and register them in the run manifest. All are imported from `reproducible_econ.emitters`.

## Tables — `LatexTableStage`

`emitters/tables.py`. Renders tidy DataFrames as standalone booktabs tables; module-level `dataframe_to_booktabs()` and `escape_latex()` back it.

Driven by the `tables` config block (see `references/configs/example_pipeline.yaml`):

- `strict` — `true` (default) raises if an artifact key is missing; `false` skips with a warning
- `exports` — one entry per table: `key` (artifact), `filename` (written under `output.tables_dir`), `caption`, `label`, `note`, `float_format`, `columns` (subset), `rename`, `alignment`, `na_rep` (default `""`), `also_csv` (optional `.csv` mirror)

## Macros — `LatexMacroStage`

`emitters/macros.py`. Emits `\newcommand` macros from rows of a tidy estimation DataFrame.

Driven by the `latex_macros` config block:

- `output_path` — defaults to `output.macros_path`
- `precision` / `short_precision` / `pval_precision` — formatting (p-values below `10**-pval_precision` render as `<0.001`)
- `fields` — per-entry, default `[coef, se, pval, n_obs]`
- `entries` — each `tidy_key`, `spec`, `key_variable`, and `name`; macros are named `<NameStem><FieldSuffix>` (e.g. `\BaselineCoef`, `\BaselineCoefShort`, `\BaselineSE`, `\BaselineP`, `\BaselineN`)

Strict checks: missing/ambiguous rows, missing columns, NaN values, digit-only or invalid names, and macro-name collisions raise `ValueError`.

## Figures — `FigureStageBase`

`emitters/figures.py`. Base stage for matplotlib figures in the optional `figures` extra (`matplotlib>=3.8`).

- Imports matplotlib lazily with the headless `Agg` backend
- On a missing install the stage skips with a warning by default; set `plotting.on_missing_matplotlib: error` to raise instead
- `plotting.style` (optional) applies a matplotlib style, `plotting.dpi` (default 200) sets the export DPI
- Subclasses implement `_plot(data, config, plt)` and save via `self._save(fig, config, filename, subdirectory=...)`, writing under `output.figures_dir`

## Claims — `ClaimCheckStage`

`emitters/claims.py`. `ClaimCheck` verifies a list of declarative claims against rows of tidy DataFrames; `ClaimCheckStage` runs it.

Driven by the `claims` config block:

- Column overrides: `spec_col`, `var_col`, `coef_col`, `pval_col`, `n_obs_col`, `date_min_col`, `date_max_col` (defaults: `spec_name`, `key_variable`, `coef`, `pval`, `n_obs`, `date_min`, `date_max`)
- `default_tol` — tolerance for `coef` comparisons (default `0.001`)
- `entries` — each with `id`, optional `description`, `tidy_key`, optional `spec` / `key_variable` selectors, and assertions:
  - `sign`: `positive` / `negative`
  - `coef` (+ optional `tol`)
  - `pval_below`, `pval_above`, `pval_between: [low, high]`
  - `n_obs`
  - `date_min` / `date_max` string matches
  - `bounds`: generic column bounds (`min` / `max`) for any numeric `coef_col`-style column

A claim is `passed`, `failed` (assertion unmet), or `unresolved` (missing/empty artifact, missing column, missing row, ambiguous match, NaN value).

- Results are written to `output.claims_path` (default `reports_dir/claims_report.json`) as `{"summary": {total, passed, failed, unresolved}, "claims": [...]}`.
- The stage publishes a `claims_results` DataFrame artifact and records summary counts in `run_manifest.json["claims"]`.
- `fail_on_error` — the default `false` logs warnings and keeps the manifest; `true` raises `ValueError` when any claim is `failed` or `unresolved`.
