# Citations

Full citations for the papers and datasets used by the projects in this repo.

## Nakamura and Steinsson (2018, QJE)

Nakamura, Emi, and Jón Steinsson. 2018. "High-Frequency Identification of Monetary Non-Neutrality: The Information Effect." *The Quarterly Journal of Economics* 133 (3): 1283–1330. doi:10.1093/qje/qjy004, https://doi.org/10.1093/qje/qjy004.

Replication data: Nakamura, Emi, and Jón Steinsson. 2018. "Replication Data for: 'High-Frequency Identification of Monetary Non-Neutrality: The Information Effect'." Harvard Dataverse. doi:10.7910/DVN/HZOXKN, https://doi.org/10.7910/DVN/HZOXKN.

Used by: `projects/nakamura_steinsson_2018/` (Table I replication).

## Bauer and Swanson (2023, NBER Macroeconomics Annual)

Bauer, Michael D., and Eric T. Swanson. 2023. "A Reassessment of Monetary Policy Surprises and High-Frequency Identification." *NBER Macroeconomics Annual* 37: 87–155. Chicago: University of Chicago Press. doi:10.1086/723574, https://doi.org/10.1086/723574.

Working paper version: NBER Working Paper 29939, https://www.nber.org/papers/w29939.

Used by: `projects/bauer_swanson_2023/` (Table 1 predictability, local projections, and Proxy-SVAR/IV analysis).

## FRBSF Monetary Policy Surprises Dataset

Bauer, Michael D., and Eric T. Swanson. "Monetary Policy Surprises." Data series, Center for Monetary Research, Federal Reserve Bank of San Francisco. https://www.frbsf.org/research-and-insights/data-and-indicators/monetary-policy-surprises/.

Files used: `monetary-policy-surprises-data_FOMC_(original).xlsx` (FOMC event-study surprises) and `monetary-policy-surprises-data_Monthly_(original).xlsx` (monthly macro series, raw and orthogonalized `mps`). See `docs/data_sources.md`.

Used by: `projects/bauer_swanson_2023/`.

## Acosta, Brennan and Jacobson (2024)

Acosta, Miguel, Connor M. Brennan, and Margaret M. Jacobson. 2024. "Constructing High-Frequency Monetary Policy Surprises from SOFR Futures." *Finance and Economics Discussion Series* 2024-034. Washington, D.C.: Board of Governors of the Federal Reserve System. doi:10.17016/FEDS.2024.034, https://doi.org/10.17016/FEDS.2024.034.

Data: https://www.federalreserve.gov/econres/feds/files/feds2024034.zip.

Used by: `projects/nakamura_steinsson_2018/` (supplies the updated Nakamura–Steinsson policy news shock `ns`; see `docs/data_sources.md`).

## Gertler and Karadi (2015, AEJ: Macroeconomics)

Gertler, Mark, and Peter Karadi. 2015. "Monetary Policy Surprises, Credit Costs, and Economic Activity." *American Economic Journal: Macroeconomics* 7 (1): 44–76. doi:10.1257/mac.20130329, https://doi.org/10.1257/mac.20130329.

Used by: `projects/gertler_karadi_2015/` (added by a parallel task; their Proxy-SVAR instrument is the FF4 futures surprise, also used in column (4) of Bauer and Swanson 2023, Table 1).
