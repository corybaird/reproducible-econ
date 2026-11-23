# Data Sources

For each project, the raw files under `data/raw/`, the public URL they come from, and the conversion to parquet. Raw data is gitignored and placed as symlinks from the companion `macroeconomics_replication` standardization pipeline.

## `projects/nakamura_steinsson_2018/`

Source papers: Nakamura and Steinsson (2018, QJE) and Acosta, Brennan and Jacobson (2024); see `docs/citations.md`.

| File | Public source | Conversion to parquet |
|---|---|---|
| `NominalYields.parquet.gzip` | NS replication archive, Harvard Dataverse doi:10.7910/DVN/HZOXKN (file `NominalYields.xls`); Gürkaynak–Sack–Swanson Svensson daily nominal zero-coupon yields | Excel sheet read as a date-indexed frame; columns `sveny01`–`sveny10` (percent) unchanged; written as gzip-compressed parquet with `date`, `country` index |
| `RealYields.parquet.gzip` | Same Dataverse DOI (file `RealYields.xls`); TIPS real zero-coupon yields | Same conversion; columns `tipsy02`–`tipsy11` (percent) unchanged |
| `FOMCmeetings.parquet.gzip` | Same Dataverse DOI (file `FOMCmeetings.xls`); FOMC meeting / conference-call flags | Same conversion; columns `unscheduled`, `fomcmeeting`, `twodays`, `isconfcall`, `weirdoct87confcall`, `minutes`, `pressconference`, `statement` unchanged |
| `ABJ-2024-monetary-policy-surprises_Data.parquet.gzip` | Acosta, Brennan and Jacobson (2024) data download, https://www.federalreserve.gov/econres/feds/files/feds2024034.zip (FEDS 2024-034) | Excel sheet read as a date-indexed frame; columns `gss_target`, `gss_path`, `ns` (percent) unchanged; written as gzip-compressed parquet |

Conversions reproduce the original columns and values 1:1; no resampling or filtering is applied at the standardization step.

## `projects/bauer_swanson_2023/`

Source dataset: FRBSF Monetary Policy Surprises (Bauer and Swanson 2023); see `docs/citations.md`. Download page: https://www.frbsf.org/research-and-insights/data-and-indicators/monetary-policy-surprises/.

| File | Public source | Conversion to parquet |
|---|---|---|
| `monetary-policy-surprises-data_FOMC_(original).parquet.gzip` | FRBSF download page, file `monetary-policy-surprises-data_FOMC_(original).xlsx`; one row per FOMC event | Excel sheet read as a date-indexed frame; columns `unscheduled`, `ff1`, `ff2`, `nfp_surp`, `ed1`–`ed4`, `sp500`, `sp500_emini` unchanged; written as gzip-compressed parquet |
| `monetary-policy-surprises-data_Monthly_(original).parquet.gzip` | FRBSF download page, file `monetary-policy-surprises-data_Monthly_(original).xlsx`; monthly macro series | Excel sheet read as a date-indexed frame; columns `unemp`, `cpi`, `nfp_surp`, `ip`, `crb_pcomm`, `ebp`, `2y_treas`, `mps`, `mps_orth`, `nfp_12m` unchanged; written as gzip-compressed parquet |

## `projects/gertler_karadi_2015/`

Added by a parallel task. Source: Gertler and Karadi (2015, AEJ: Macroeconomics); see `docs/citations.md`.
