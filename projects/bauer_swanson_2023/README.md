# Bauer and Swanson (2023) — Monetary Policy Surprises Multi-Model Pipeline (Advanced Project)

Multi-model applied pipeline built on the FRBSF monetary-policy-surprises dataset from Bauer and Swanson (2023), *"A Reassessment of Monetary Policy Surprises and High-Frequency Identification"* (*NBER Macroeconomics Annual* 37, 87–155).

## Pipeline Stages

1. `prepare_macro_data` (`data`, cached): Loads FRBSF FOMC event-study and monthly macro series (`1988-02` to `2019-12`), computes `100 * ln(IP)` and `100 * ln(CPI)`, and writes summary statistics.
2. `align_and_test_shocks` (`shocks`, cached): Extracts the first principal component of Eurodollar futures surprises (`ed1`–`ed4`) via `PCAModel`, aggregates it to monthly frequency alongside FRBSF `mps` and `mps_orth`, and tests both Table 1 payroll-news predictability (`raw_mps`, `pca_mps`) and out-of-set exogeneity on lagged EBP and YoY CPI inflation (`RobustOLSModel`, HC1 SEs).
3. `estimate_lp_models` (`estimate`, cached): Estimates Jordà local projections (`LocalProjectionsModel`, HAC SEs, horizons `0..24`) for `treas_2y`, `log_ip`, `log_cpi`, `unemp`, and `ebp` comparing orthogonalized `mps_orth` (6 lags), raw `mps` (6 lags), and a 12-lag robustness specification.
4. `estimate_structural_models` (`estimate`, cached): Estimates a 5-variable external-instrument Proxy-SVAR (`ProxySVARModel`, 6-lag baseline, raw-shock comparison, and 12-lag robustness) and `LocalProjectionsIVModel` instrumenting the 2-year Treasury yield with `mps_orth`, all scaled to a +25 bp policy-rate impact.
5. `export_tables` (`report`): Writes four booktabs LaTeX tables (`summary_stats.tex`, `shock_predictability.tex`, `lp_headline.tex`, `model_comparison.tex`).
6. `plot_irfs` (`report`): Emits `figures/lp_orth_vs_raw_irfs.png` and `figures/structural_irfs.png` (skips cleanly if `matplotlib` is absent).
7. `export_macros` (`report`): Writes `\newcommand` paper macros to `macros.tex`.
8. `check_claims` (`report`): Evaluates seven headline Bauer and Swanson (2023) empirical claims and writes `claims_report.json`.

## Required Raw Data

Raw data sources and parquet conversions: [docs/data_sources.md](../../docs/data_sources.md). Full citation: Bauer and Swanson (2023) in [docs/citations.md](../../docs/citations.md).

Place the two standardized FRBSF parquet files under `data/raw/bauer_swanson_2023/`:

- `monetary-policy-surprises-data_FOMC_(original).parquet.gzip`
- `monetary-policy-surprises-data_Monthly_(original).parquet.gzip`

## Run Command

```bash
uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/bauer_swanson_2023/pipeline.yaml
```

Outputs are written to `reports/bauer_swanson_2023/` and cached artifacts to `.cache/bauer_swanson_2023/`.
