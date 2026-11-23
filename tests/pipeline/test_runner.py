import json
import os
import subprocess
import sys

import pandas as pd
import pytest

from reproducible_econ import BaseStage, PipelineRunner


class BuildFrameStage(BaseStage):
    def run(self, data, config):
        n = config["params"]["n"]
        data["raw"] = pd.DataFrame({"x": list(range(1, n + 1))})
        return data


class ScaleFrameStage(BaseStage):
    def run(self, data, config):
        scale = config["params"]["scale"]
        out = data["raw"].copy()
        out["y"] = out["x"] * scale
        data["scaled"] = out
        return data


class OptionalSummaryStage(BaseStage):
    def run(self, data, config):
        data["summary"] = pd.DataFrame({"total": [data["scaled"]["y"].sum()]})
        return data


def _write_pipeline_yaml(tmp_path, include_summary=True, scale=2, module_name=None):
    mod = module_name or __name__
    cfg_path = tmp_path / "pipeline.yaml"
    cfg_path.write_text(
        f"params:\n"
        f"  n: 4\n"
        f"  scale: {scale}\n"
        f"flags:\n"
        f"  summary: {'true' if include_summary else 'false'}\n"
        f"output:\n"
        f"  cache_dir: {tmp_path / 'cache'}\n"
        f"  reports_dir: {tmp_path / 'reports'}\n"
        f"default_module: {mod}\n"
        f"stages:\n"
        f"  - name: build\n"
        f"    class: BuildFrameStage\n"
        f"    phase: data\n"
        f"    produces: [raw]\n"
        f"    cache: true\n"
        f"    cache_inputs: [params.n]\n"
        f"  - name: scale\n"
        f"    class: ScaleFrameStage\n"
        f"    phase: transform\n"
        f"    requires: [raw]\n"
        f"    produces: [scaled]\n"
        f"    cache: true\n"
        f"    cache_inputs: [params.scale]\n"
        f"  - name: summarize\n"
        f"    class: OptionalSummaryStage\n"
        f"    phase: report\n"
        f"    requires: [scaled]\n"
        f"    produces: [summary]\n"
        f"    enabled_config: flags.summary\n"
        f"    cache: false\n",
        encoding="utf-8",
    )
    return cfg_path


def test_runner_cold_warm_no_cache_and_targets(tmp_path):
    cfg = _write_pipeline_yaml(tmp_path, include_summary=True)

    cold = PipelineRunner(cfg)
    data_cold = cold.run()
    assert data_cold["summary"]["total"].tolist() == [20]
    assert cold.last_manifest["stages"]["build"]["status"] == "executed"
    assert cold.last_manifest["stages"]["scale"]["status"] == "executed"
    assert cold.manifest_path.is_file()

    warm = PipelineRunner(cfg)
    warm.run()
    assert warm.last_manifest["stages"]["build"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["scale"]["status"] == "cache_hit"
    assert warm.last_manifest["stages"]["build"]["elapsed_sec"] == 0.0

    # Target subset with upstream closure
    targeted = PipelineRunner(cfg, targets=["scale"])
    targeted.run()
    assert list(targeted.last_manifest["stages"].keys()) == ["build", "scale"]
    assert targeted.last_manifest["targets"] == ["scale"]

    # --no-cache forces re-execution
    forced = PipelineRunner(cfg, no_cache=True)
    forced.run()
    assert forced.last_manifest["stages"]["build"]["status"] == "executed"
    assert forced.last_manifest["stages"]["build"]["cache_miss_reason"] == "no_cache_flag"


def test_runner_records_disabled_stage_as_skipped(tmp_path):
    cfg = _write_pipeline_yaml(tmp_path, include_summary=False)
    runner = PipelineRunner(cfg)
    runner.run()
    assert runner.last_manifest["stages"]["summarize"]["status"] == "skipped"
    assert runner.last_manifest["stages"]["summarize"]["elapsed_sec"] == 0.0


def test_runner_missing_stages_raises(tmp_path):
    bad_cfg = tmp_path / "empty.yaml"
    bad_cfg.write_text("project:\n  name: empty\n", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty 'stages'"):
        PipelineRunner(bad_cfg).run()


def test_runner_cli_subprocess_smoke(tmp_path):
    stage_mod = tmp_path / "cli_stages.py"
    stage_mod.write_text(
        "import pandas as pd\n"
        "from reproducible_econ import BaseStage\n"
        "class MakeOne(BaseStage):\n"
        "    def run(self, data, config):\n"
        "        data['out'] = pd.DataFrame({'v': [config['val']]})\n"
        "        return data\n",
        encoding="utf-8",
    )
    cfg = tmp_path / "cli.yaml"
    cfg.write_text(
        f"val: 7\n"
        f"output:\n"
        f"  cache_dir: {tmp_path / 'cache'}\n"
        f"  reports_dir: {tmp_path / 'reports'}\n"
        f"stages:\n"
        f"  - name: make\n"
        f"    module: cli_stages\n"
        f"    class: MakeOne\n"
        f"    produces: [out]\n"
        f"    cache: true\n",
        encoding="utf-8",
    )
    full_env = dict(os.environ)
    existing_pp = full_env.get("PYTHONPATH", "")
    full_env["PYTHONPATH"] = f"{tmp_path}{os.pathsep}{existing_pp}" if existing_pp else str(tmp_path)
    proc = subprocess.run(
        [sys.executable, "-m", "reproducible_econ.pipeline.runner", "--config", str(cfg)],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "RuntimeWarning" not in proc.stderr
    manifest = json.loads((tmp_path / "reports" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["stages"]["make"]["status"] == "executed"


def test_lazy_pipeline_runner_export_and_unknown_attr():
    import reproducible_econ

    assert reproducible_econ.PipelineRunner is PipelineRunner
    with pytest.raises(AttributeError, match="no attribute 'NotARealExport'"):
        _ = reproducible_econ.NotARealExport
