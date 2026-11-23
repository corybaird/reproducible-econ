# Roadmap

Status: `0.1.0` beta, stage runner, cache, manifest, emitters and claim checks on three applied replications

## 0.1.x - hardening
- Publish to PyPI
- Data download and standardization scripts for each applied project
- More cache artifact types beyond pandas DataFrames

## 0.2 - from paper to pipeline
- Claim-check drafter: turn claims from [econ-pdf-extract](https://github.com/corybaird/econ-pdf-extract) into `claims:` entries
- Project scaffolder: create `projects/<paper>/` with `pipeline.yaml`, `stages.py` and README from a paper registry entry
- More replications with published or MATLAB / Stata reference values

## 0.3 - verified evidence
- Mark causal claims as verified when their claim check passes, and record it in the manifest
- Manifest diff between runs, so a changed number points to the stage and input that moved it
- Overleaf-ready export bundle (tables, macros, claims report)

## Principles
- Deterministic and config-driven, no LLM or agent dependencies in the core package
- Every output traceable to its inputs, config and code version
- Small core dependencies: pandas, pyarrow, pyyaml
