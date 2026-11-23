import json
from pathlib import Path

import pandas as pd

from reproducible_econ import StageExecutor


class MultiplyValues:
    def run(self, data, config):
        output = data["input"].copy()
        output["value"] = output["value"] * config["factor"]
        data["output"] = output
        return data


def config(tmp_path, factor=2):
    return {"factor": factor, "output": {"cache_dir": str(tmp_path / "cache"), "reports_dir": str(tmp_path / "reports")}}


def test_cache_and_config_invalidation(tmp_path):
    data = {"input": pd.DataFrame({"value": [1, 2, 3]})}
    first = StageExecutor(config(tmp_path), "params.yaml")
    first.run("multiply", MultiplyValues(), data, cache_inputs=["factor"], cache=True, output_keys=["output"])
    assert first.manifest["stages"]["multiply"]["status"] == "executed"
    second_data = {"input": data["input"]}
    second = StageExecutor(config(tmp_path), "params.yaml")
    second.run("multiply", MultiplyValues(), second_data, cache_inputs=["factor"], cache=True, output_keys=["output"])
    assert second.manifest["stages"]["multiply"]["status"] == "cache_hit"
    pd.testing.assert_frame_equal(second_data["output"], data["output"])
    changed = StageExecutor(config(tmp_path, factor=3), "params.yaml")
    changed.run("multiply", MultiplyValues(), data, cache_inputs=["factor"], cache=True, output_keys=["output"])
    assert changed.manifest["stages"]["multiply"]["status"] == "executed"
    assert data["output"]["value"].tolist() == [3, 6, 9]
    manifest = changed.finalize()
    assert json.loads(manifest.read_text())["stage_timings_sec"]["multiply"] >= 0


def test_source_checksum_invalidation(tmp_path):
    source = Path(tmp_path / "input.txt")
    source.write_text("first")
    settings = {"factor": 2, "source": str(source), "output": {"cache_dir": str(tmp_path / "cache")}}
    executor = StageExecutor(settings, "params.yaml")
    data = {"input": pd.DataFrame({"value": [1]})}
    executor.run("multiply", MultiplyValues(), data, cache_inputs=["source"], cache=True, output_keys=["output"])
    first_fingerprint = executor.manifest["stages"]["multiply"]["fingerprint"]
    source.write_text("second")
    executor = StageExecutor(settings, "params.yaml")
    executor.run("multiply", MultiplyValues(), data, cache_inputs=["source"], cache=True, output_keys=["output"])
    assert executor.manifest["stages"]["multiply"]["fingerprint"] != first_fingerprint


def test_executor_no_cache_flag_and_miss_reason(tmp_path):
    data = {"input": pd.DataFrame({"value": [2, 4]})}
    cold = StageExecutor(config(tmp_path), "params.yaml")
    cold.run("multiply", MultiplyValues(), data, cache_inputs=["factor"], cache=True, output_keys=["output"])
    assert cold.manifest["stages"]["multiply"]["cache_miss_reason"] == "no_cache"

    forced = StageExecutor(config(tmp_path), "params.yaml", no_cache=True)
    forced.run("multiply", MultiplyValues(), data, cache_inputs=["factor"], cache=True, output_keys=["output"])
    assert forced.manifest["stages"]["multiply"]["status"] == "executed"
    assert forced.manifest["stages"]["multiply"]["cache_miss_reason"] == "no_cache_flag"


def test_executor_corrupt_cache_recovers_cleanly(tmp_path):
    data = {"input": pd.DataFrame({"value": [5, 10]})}
    first = StageExecutor(config(tmp_path), "params.yaml")
    first.run("multiply", MultiplyValues(), data, cache_inputs=["factor"], cache=True, output_keys=["output"])
    fp = first.manifest["stages"]["multiply"]["fingerprint"]
    parquet_path = tmp_path / "cache" / "multiply" / fp / "output.parquet"
    parquet_path.write_bytes(b"corrupted-bytes")

    recovered = StageExecutor(config(tmp_path), "params.yaml")
    recovered.run("multiply", MultiplyValues(), {"input": data["input"]}, cache_inputs=["factor"], cache=True, output_keys=["output"])
    assert recovered.manifest["stages"]["multiply"]["status"] == "executed"
    assert recovered.manifest["stages"]["multiply"]["cache_miss_reason"] == "checksum_mismatch: output"

    warm = StageExecutor(config(tmp_path), "params.yaml")
    warm.run("multiply", MultiplyValues(), {"input": data["input"]}, cache_inputs=["factor"], cache=True, output_keys=["output"])
    assert warm.manifest["stages"]["multiply"]["status"] == "cache_hit"


def test_executor_omitted_cache_inputs_hashes_config_minus_output_and_cache(tmp_path):
    data = {"input": pd.DataFrame({"value": [1, 2]})}
    cfg1 = {
        "factor": 2,
        "output": {"cache_dir": str(tmp_path / "cache"), "reports_dir": str(tmp_path / "reports_a")},
        "cache": {"retain_prior_fingerprints": 2},
    }
    e1 = StageExecutor(cfg1, "params.yaml")
    e1.run("multiply", MultiplyValues(), data, cache=True, output_keys=["output"])
    assert e1.manifest["stages"]["multiply"]["status"] == "executed"

    # Changing reports_dir / cache settings still hits cache
    cfg2 = {
        "factor": 2,
        "output": {"cache_dir": str(tmp_path / "cache"), "reports_dir": str(tmp_path / "reports_b")},
        "cache": {"retain_prior_fingerprints": 5},
    }
    e2 = StageExecutor(cfg2, "params.yaml")
    e2.run("multiply", MultiplyValues(), {"input": data["input"]}, cache=True, output_keys=["output"])
    assert e2.manifest["stages"]["multiply"]["status"] == "cache_hit"

    # Changing factor invalidates with fingerprint_changed: config
    cfg3 = {**cfg2, "factor": 9}
    e3 = StageExecutor(cfg3, "params.yaml")
    e3.run("multiply", MultiplyValues(), {"input": data["input"]}, cache=True, output_keys=["output"])
    assert e3.manifest["stages"]["multiply"]["status"] == "executed"
    assert e3.manifest["stages"]["multiply"]["cache_miss_reason"] == "fingerprint_changed: config"
