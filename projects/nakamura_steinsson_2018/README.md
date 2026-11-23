# Nakamura and Steinsson (2018) — High-Frequency Yield-Curve Event Study (Basic Project)

Single-model applied replication of **Table I** from Nakamura and Steinsson (2018), *"High-Frequency Identification of Monetary Non-Neutrality: The Information Effect"* (*Quarterly Journal of Economics* 133(3), 1283–1330).

## Pipeline Stages

1. `prepare_event_data` (`data`, cached): Loads daily nominal Treasury yields (`sveny02`–`sveny10`), TIPS real yields (`tipsy02`–`tipsy10`), FOMC meeting flags, and the `ns` policy news shock; computes daily yield and breakeven-inflation changes on scheduled FOMC meeting days (2000–2014, excluding July 2008–June 2009).
2. `estimate_yield_responses` (`estimate`, cached): Estimates one econometric model (`stats_transformer.models.RobustOLSModel`, HC1 SEs) across 2Y, 3Y, 5Y, and 10Y nominal, real, and breakeven yield responses.
3. `export_tables` (`report`): Writes booktabs LaTeX tables (`tables/summary_stats.tex`, `tables/yield_responses.tex`).
4. `export_macros` (`report`): Writes `\newcommand` paper macros to `macros.tex`.
5. `check_claims` (`report`): Checks five headline Table I claims against the published QJE values and emits `claims_report.json`.

## Required Raw Data

Raw data sources and parquet conversions: [docs/data_sources.md](../../docs/data_sources.md). Full citation: Nakamura and Steinsson (2018) in [docs/citations.md](../../docs/citations.md).

Place the four standardized parquet files under `data/raw/nakamura_steinsson_2018/`:

- `NominalYields.parquet.gzip`
- `RealYields.parquet.gzip`
- `FOMCmeetings.parquet.gzip`
- `ABJ-2024-monetary-policy-surprises_Data.parquet.gzip`

## Run Command

```bash
uv run --with "stats-transformer>=1.11.1" --extra figures \
  python -m reproducible_econ.pipeline.runner --config projects/nakamura_steinsson_2018/pipeline.yaml
```

Outputs are written to `reports/nakamura_steinsson_2018/` and cached artifacts to `.cache/nakamura_steinsson_2018/`.
