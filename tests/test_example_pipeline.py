import json
from pathlib import Path

import yaml

from reproducible_econ import PipelineRunner

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CONFIG = REPO_ROOT / "references" / "configs" / "example_pipeline.yaml"


def _copy_config_to_tmp(tmp_path, overrides=None):
    raw = yaml.safe_load(EXAMPLE_CONFIG.read_text(encoding="utf-8"))
    raw["output"]["cache_dir"] = str(tmp_path / "cache")
    raw["output"]["reports_dir"] = str(tmp_path / "reports")
    for section, updates in (overrides or {}).items():
        raw[section].update(updates)
    target = tmp_path / "example_pipeline.yaml"
    target.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return target


def test_example_pipeline_cold_warm_diff_and_no_cache(tmp_path):
    cfg_path = _copy_config_to_tmp(tmp_path)
    reports_dir = tmp_path / "reports"

    # 1. Cold run
    cold = PipelineRunner(cfg_path)
    cold.run()
    assert cold.last_manifest["stages"]["prepare_data"]["status"] == "executed"
    assert cold.last_manifest["stages"]["estimate_ols"]["status"] == "executed"
    assert cold.last_manifest["claims"]["passed"] == 2
    assert cold.last_manifest["claims"]["failed"] == 0
    assert (reports_dir / "tables" / "summary_stats.tex").is_file()
    assert (reports_dir / "tables" / "phillips_estimates.tex").is_file()
    assert (reports_dir / "macros.tex").is_file()
    assert (reports_dir / "claims_report.json").is_file()
    assert (reports_dir / "run_manifest.json").is_file()
    macros_before = (reports_dir / "macros.tex").read_text(encoding="utf-8")
    assert r"\newcommand{\BaselineCoef}" in macros_before

    # 2. Warm rerun hits cache on data/estimation AND marks emitters up_to_date
    warm = PipelineRunner(cfg_path)
    warm.run()
    assert warm.last_manifest["stages"]["prepare_data"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["prepare_data"]["elapsed_sec"] == 0.0
    assert warm.last_manifest["stages"]["estimate_ols"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["estimate_ols"]["elapsed_sec"] == 0.0
    assert warm.last_manifest["stages"]["export_tables"]["status"] == "up_to_date"
    assert warm.last_manifest["stages"]["export_macros"]["status"] == "up_to_date"
    assert warm.last_manifest["stages"]["check_claims"]["status"] == "up_to_date"
    assert warm.last_manifest["claims"]["passed"] == 2
    assert "macros.tex" in warm.last_manifest["outputs"]

    # 2b. Deleting macros.tex makes ONLY export_macros re-run
    (reports_dir / "macros.tex").unlink()
    rebuilt = PipelineRunner(cfg_path)
    rebuilt.run()
    assert rebuilt.last_manifest["stages"]["prepare_data"]["status"] == "cache_hit"
    assert rebuilt.last_manifest["stages"]["estimate_ols"]["status"] == "cache_hit"
    assert rebuilt.last_manifest["stages"]["export_tables"]["status"] == "up_to_date"
    assert rebuilt.last_manifest["stages"]["check_claims"]["status"] == "up_to_date"
    assert rebuilt.last_manifest["stages"]["export_macros"]["status"] == "executed"
    assert rebuilt.last_manifest["stages"]["export_macros"]["cache_miss_reason"] == "missing_output: macros.tex"
    assert (reports_dir / "macros.tex").is_file()

    # 3. One-line config change (winsorize_pct) keeps prepare_data cached and invalidates estimate_ols + emitters
    cfg_diff = _copy_config_to_tmp(tmp_path, overrides={"estimation": {"winsorize_pct": 0.05}})
    diff_run = PipelineRunner(cfg_diff)
    diff_run.run()
    assert diff_run.last_manifest["stages"]["prepare_data"]["status"] == "cache_hit"
    assert diff_run.last_manifest["stages"]["estimate_ols"]["status"] == "executed"
    assert diff_run.last_manifest["stages"]["estimate_ols"]["cache_miss_reason"] == "fingerprint_changed: config"
    assert diff_run.last_manifest["stages"]["export_tables"]["status"] == "executed"
    assert diff_run.last_manifest["stages"]["export_macros"]["status"] == "executed"
    assert diff_run.last_manifest["stages"]["check_claims"]["status"] == "executed"
    macros_after = (reports_dir / "macros.tex").read_text(encoding="utf-8")
    assert macros_after != macros_before

    # 4. --no-cache re-executes all cached and emitter stages
    forced = PipelineRunner(cfg_diff, no_cache=True)
    forced.run()
    assert forced.last_manifest["stages"]["prepare_data"]["status"] == "executed"
    assert forced.last_manifest["stages"]["prepare_data"]["cache_miss_reason"] == "no_cache_flag"
    assert forced.last_manifest["stages"]["estimate_ols"]["status"] == "executed"
    assert forced.last_manifest["stages"]["estimate_ols"]["cache_miss_reason"] == "no_cache_flag"
    assert forced.last_manifest["stages"]["export_macros"]["status"] == "executed"
    assert forced.last_manifest["stages"]["export_macros"]["cache_miss_reason"] == "no_cache_flag"
    manifest_disk = json.loads((reports_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest_disk["no_cache"] is True


def test_example_pipeline_from_different_cwd_lands_under_repo_root(tmp_path, monkeypatch):
    fake_repo = tmp_path / "fake_repo"
    cfg_dir = fake_repo / "references" / "configs"
    cfg_dir.mkdir(parents=True)
    (fake_repo / "pyproject.toml").write_text("[project]\nname = 'fake'\n", encoding="utf-8")
    cfg_copy = cfg_dir / "example_pipeline.yaml"
    cfg_copy.write_text(EXAMPLE_CONFIG.read_text(encoding="utf-8"), encoding="utf-8")

    other_cwd = tmp_path / "outside_cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    runner = PipelineRunner(cfg_copy)
    runner.run()

    repo_reports = fake_repo / "reports" / "macro_demo"
    repo_cache = fake_repo / ".cache" / "macro_demo"
    assert (repo_reports / "run_manifest.json").is_file()
    assert (repo_reports / "tables" / "summary_stats.tex").is_file()
    assert (repo_reports / "tables" / "phillips_estimates.tex").is_file()
    assert (repo_reports / "macros.tex").is_file()
    assert (repo_reports / "claims_report.json").is_file()
    assert repo_cache.is_dir()
    assert not (other_cwd / "reports").exists()
    assert not (other_cwd / ".cache").exists()
