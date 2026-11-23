import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

from reproducible_econ import ConfigLoader, PipelineRunner, StageDefinition, StageGraph

REPO_ROOT = Path(__file__).resolve().parents[1]
NS_CONFIG = REPO_ROOT / "projects" / "nakamura_steinsson_2018" / "pipeline.yaml"
BS_CONFIG = REPO_ROOT / "projects" / "bauer_swanson_2023" / "pipeline.yaml"

NS_DATA_FILES = (
    REPO_ROOT / "data" / "raw" / "nakamura_steinsson_2018" / "NominalYields.parquet.gzip",
    REPO_ROOT / "data" / "raw" / "nakamura_steinsson_2018" / "RealYields.parquet.gzip",
    REPO_ROOT / "data" / "raw" / "nakamura_steinsson_2018" / "FOMCmeetings.parquet.gzip",
    REPO_ROOT / "data" / "raw" / "nakamura_steinsson_2018" / "ABJ-2024-monetary-policy-surprises_Data.parquet.gzip",
)
BS_DATA_FILES = (
    REPO_ROOT / "data" / "raw" / "bauer_swanson_2023" / "monetary-policy-surprises-data_FOMC_(original).parquet.gzip",
    REPO_ROOT / "data" / "raw" / "bauer_swanson_2023" / "monetary-policy-surprises-data_Monthly_(original).parquet.gzip",
)


def _has_files(paths):
    return all(path.is_file() for path in paths)


def _has_stats_transformer():
    return importlib.util.find_spec("stats_transformer") is not None


def _copy_config_to_tmp(src_config, tmp_path):
    raw = yaml.safe_load(src_config.read_text(encoding="utf-8"))
    raw["output"]["cache_dir"] = str(tmp_path / "cache")
    raw["output"]["reports_dir"] = str(tmp_path / "reports")
    for key, val in list((raw.get("data") or {}).items()):
        if isinstance(val, str) and "${project_root}" in val:
            raw["data"][key] = val.replace("${project_root}", str(REPO_ROOT))
    target = tmp_path / src_config.name
    target.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return target


@pytest.mark.parametrize("config_path", [NS_CONFIG, BS_CONFIG])
def test_applied_project_config_and_dag_valid(config_path):
    config = ConfigLoader().load(config_path)
    default_module = config.get("default_module")
    definitions = [
        StageDefinition.from_dict(spec, default_order=idx, default_module=default_module)
        for idx, spec in enumerate(config["stages"])
    ]
    graph = StageGraph(definitions)
    selected = graph.resolve()
    graph.validate_enabled(selected, config)
    assert len(selected) == len(config["stages"])


def test_missing_data_helper_detects_absent_files(tmp_path):
    assert not _has_files((tmp_path / "missing.parquet.gzip",))


def test_runner_imports_project_stages_from_different_cwd(tmp_path, monkeypatch):
    fake_repo = tmp_path / "fake_repo"
    proj_dir = fake_repo / "cwd_demo_pkg" / "subproj"
    proj_dir.mkdir(parents=True)
    (fake_repo / "pyproject.toml").write_text("[project]\nname = 'fake'\n", encoding="utf-8")
    (proj_dir / "stages.py").write_text(
        "import pandas as pd\n"
        "from reproducible_econ.pipeline.stage import BaseStage\n\n"
        "class BuildStage(BaseStage):\n"
        "    def run(self, data, config):\n"
        "        data['out'] = pd.DataFrame({'x': [1, 2, 3]})\n"
        "        return data\n",
        encoding="utf-8",
    )
    cfg_path = proj_dir / "pipeline.yaml"
    cfg_path.write_text(
        "output:\n"
        "  cache_dir: .cache/cwd_demo\n"
        "  reports_dir: reports/cwd_demo\n"
        "default_module: cwd_demo_pkg.subproj.stages\n"
        "stages:\n"
        "  - name: build\n"
        "    class: BuildStage\n"
        "    produces: [out]\n"
        "    cache: true\n",
        encoding="utf-8",
    )
    other_cwd = tmp_path / "outside_cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if Path(p).resolve() != fake_repo.resolve()])

    try:
        runner = PipelineRunner(cfg_path)
        result = runner.run()
        assert list(result["out"]["x"]) == [1, 2, 3]
        assert (fake_repo / "reports" / "cwd_demo" / "run_manifest.json").is_file()
    finally:
        for mod_name in [name for name in list(sys.modules) if name == "cwd_demo_pkg" or name.startswith("cwd_demo_pkg.")]:
            sys.modules.pop(mod_name, None)


@pytest.mark.skipif(not _has_files(NS_DATA_FILES), reason="Nakamura-Steinsson raw data not present under data/raw/")
@pytest.mark.skipif(not _has_stats_transformer(), reason="stats-transformer not installed in active environment")
def test_nakamura_steinsson_smoke_cold_and_warm(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    cfg_path = _copy_config_to_tmp(NS_CONFIG, tmp_path)
    reports_dir = tmp_path / "reports"

    cold = PipelineRunner(cfg_path)
    cold.run()
    assert cold.last_manifest["stages"]["prepare_event_data"]["status"] == "executed"
    assert cold.last_manifest["stages"]["estimate_yield_responses"]["status"] == "executed"
    assert cold.last_manifest["claims"]["passed"] == 5
    assert cold.last_manifest["claims"]["failed"] == 0
    assert (reports_dir / "tables" / "yield_responses.tex").is_file()
    assert (reports_dir / "macros.tex").is_file()
    assert (reports_dir / "claims_report.json").is_file()

    warm = PipelineRunner(cfg_path)
    warm.run()
    assert warm.last_manifest["stages"]["prepare_event_data"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["estimate_yield_responses"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["export_tables"]["status"] == "up_to_date"
    assert warm.last_manifest["stages"]["export_macros"]["status"] == "up_to_date"
    assert warm.last_manifest["stages"]["check_claims"]["status"] == "up_to_date"


@pytest.mark.skipif(not _has_files(BS_DATA_FILES), reason="Bauer-Swanson raw data not present under data/raw/")
@pytest.mark.skipif(not _has_stats_transformer(), reason="stats-transformer not installed in active environment")
def test_bauer_swanson_smoke_cold_and_warm(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    cfg_path = _copy_config_to_tmp(BS_CONFIG, tmp_path)
    reports_dir = tmp_path / "reports"

    cold = PipelineRunner(cfg_path)
    cold.run()
    assert cold.last_manifest["stages"]["prepare_macro_data"]["status"] == "executed"
    assert cold.last_manifest["stages"]["align_and_test_shocks"]["status"] == "executed"
    assert cold.last_manifest["stages"]["estimate_lp_models"]["status"] == "executed"
    assert cold.last_manifest["stages"]["estimate_structural_models"]["status"] == "executed"
    assert cold.last_manifest["claims"]["passed"] == 7
    assert cold.last_manifest["claims"]["failed"] == 0
    assert (reports_dir / "tables" / "shock_predictability.tex").is_file()
    assert (reports_dir / "tables" / "model_comparison.tex").is_file()
    assert (reports_dir / "macros.tex").is_file()
    assert (reports_dir / "claims_report.json").is_file()

    warm = PipelineRunner(cfg_path)
    warm.run()
    assert warm.last_manifest["stages"]["prepare_macro_data"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["align_and_test_shocks"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["estimate_lp_models"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["estimate_structural_models"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["export_tables"]["status"] == "up_to_date"
    assert warm.last_manifest["stages"]["export_macros"]["status"] == "up_to_date"
    assert warm.last_manifest["stages"]["check_claims"]["status"] == "up_to_date"
