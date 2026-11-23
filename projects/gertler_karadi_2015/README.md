# Gertler and Karadi (2015) — Proxy-SVAR with a High-Frequency Instrument

Applied pipeline replicating the proxy-SVAR of Gertler and Karadi (2015), *"Monetary Policy Surprises, Credit Costs, and Economic Activity"* (*American Economic Journal: Macroeconomics* 7(1), 44–76, doi:[10.1257/mac.20130329](https://doi.org/10.1257/mac.20130329)).

A four-variable monthly VAR in `gs1` (1-year Treasury rate), `logcpi` (log CPI), `logip` (log industrial production), and `ebp` (excess bond premium) is estimated with 12 lags and a constant. The `gs1` equation is instrumented with `ff4_tc`, the high-frequency fed funds futures surprise around FOMC announcements (Gertler-Karadi external-instrument identification, following Mertens and Ravn 2014).

## Pipeline Stages

1. `prepare_gk_panel` (`data`, cached): Loads the Gertler-Karadi AEJ replication workbook `GK2015_Data.xlsx`, selects variables by mnemonic, and maps the `123456789` missing-value sentinel to NaN.
2. `estimate_proxy_svar` (`estimate`, cached): Fits `ProxySVARModel` (12 lags, `ff4_tc` instrument), computes impulse responses to a one-standard-deviation monetary policy shock for horizons 0–47, and runs the first-stage OLS regression of the instrumented `gs1` VAR residual on `ff4_tc` (F statistic, t-stat, R², 270 common observations).
3. `export_irf_table` (`report`): Writes `tables/gk_irf_headline.tex` with responses at horizons 0, 3, 6, 12, and 24 months.
4. `plot_irfs` (`report`): Emits `figures/gk_psvar_irfs.png` (skips cleanly if `matplotlib` is absent).
5. `export_macros` (`report`): Writes `\newcommand` paper macros to `macros.tex`.
6. `check_claims` (`report`): Compares the Python first-stage F statistic and impulse responses (horizons 0, 12, 24 for `gs1`, `logip`, `ebp`) against the recorded MATLAB run and writes `claims_report.json`.

## Validation Against the MATLAB Reference

Every claim is checked against a recorded MATLAB R2025b run of VAR-Toolbox 4.0 (`VARmodel` with `ident = 'iv'`), driven by `tests/external_benchmarks/matlab/drivers/st_ref_gk2015_iv.m` in the [stats-transformer](https://github.com/corybaird/stats-transformer) repository, with outputs stored in `tests/external_benchmarks/matlab/gk2015_iv.json` (keys `IR`, `B`, `first_stage_F`, `first_stage_beta`, ...). The Python pipeline reproduces the MATLAB first-stage F statistic and impulse responses to within float round-off (see `claims_report.json` for the full comparison).

## Required Raw Data

Place the Gertler-Karadi replication dataset at `data/raw/gertler_karadi_2015/GK2015_Data.xlsx`:

- Source: Gertler-Karadi AEJ:Macroeconomics replication files (AEJ website, doi 10.1257/mac.20130329, paper code `Replic/GK2015`).
- File: `GK2015_Data.xlsx`, sheet `Sheet1`, with mnemonic row 2 and monthly data 1979m7–2012m6 for `logcpi`, `logip`, `gs1`, `ebp`, and `ff4_tc`.

## Run Command

```bash
uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/gertler_karadi_2015/pipeline.yaml
```

Outputs are written to `reports/gertler_karadi_2015/` (tables, figure, macros, `claims_report.json`, `run_manifest.json`) and cached artifacts to `.cache/gertler_karadi_2015/`.
