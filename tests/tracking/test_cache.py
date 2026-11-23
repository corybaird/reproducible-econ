import json
import os
import time

import pandas as pd
import pytest

from reproducible_econ.tracking.cache import StageCache
from reproducible_econ.tracking.fingerprint import CacheFingerprint
from reproducible_econ.tracking.metadata import CacheArtifactMetadata


class SampleStageA:
    def run(self, data, config):
        return data


class SampleStageB:
    def run(self, data, config):
        return dict(data)


def test_parquet_dtype_round_trip_metadata(tmp_path):
    frames = {
        "primitives": pd.DataFrame({"i": [1, 2, 3], "f": [1.25, 2.5, 3.75], "s": ["a", "b", "c"]}),
        "datetime": pd.DataFrame({"dt": pd.date_range("2020-01-01", periods=3)}),
        "category": pd.DataFrame({"cat": pd.Categorical(["low", "high", "low"])}),
        "multiindex": pd.DataFrame(
            {"val": [10.0, 20.0, 30.0]},
            index=pd.MultiIndex.from_tuples([("A", 1), ("A", 2), ("B", 1)], names=["econ", "q"]),
        ),
        "obj_str": pd.DataFrame({"txt": pd.Series(["x", "y", None], dtype=object)}),
    }
    cache = StageCache(tmp_path / "cache")
    data = dict(frames)
    keys = list(frames.keys())
    cache.save("dtypes_stage", "fp001", data, keys, component_hashes={"config": "abc"})

    loaded = {}
    hit, reason = cache.load("dtypes_stage", "fp001", loaded, keys, component_hashes={"config": "abc"})
    assert hit is True
    assert reason is None
    for key in keys:
        pd.testing.assert_frame_equal(loaded[key], data[key])


def test_tamper_detection_checksum_and_metadata(tmp_path):
    cache = StageCache(tmp_path / "cache")
    df = pd.DataFrame({"x": [1, 2, 3]})
    fp_dir = cache.save("stage", "fp1", {"df": df}, ["df"], component_hashes={"config": "111"})

    # Tamper parquet bytes directly -> checksum_mismatch
    parquet_path = fp_dir / "df.parquet"
    parquet_path.write_bytes(parquet_path.read_bytes() + b"corrupt")
    hit, reason = cache.load("stage", "fp1", {}, ["df"])
    assert hit is False
    assert reason == "checksum_mismatch: df"

    # Re-save cleanly over corrupted fp_dir (atomic swap recovery)
    cache.save("stage", "fp1", {"df": df}, ["df"], component_hashes={"config": "111"})
    hit, reason = cache.load("stage", "fp1", {}, ["df"])
    assert hit is True
    assert reason is None

    # Tamper metadata rows while keeping file_sha256 valid -> metadata_mismatch
    meta_path = fp_dir / "metadata.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["artifacts"]["df"]["rows"] = 999
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    hit, reason = cache.load("stage", "fp1", {}, ["df"])
    assert hit is False
    assert reason == "metadata_mismatch: df"

    # Missing parquet artifact -> missing_artifact
    parquet_path.unlink()
    hit, reason = cache.load("stage", "fp1", {}, ["df"])
    assert hit is False
    assert reason == "missing_artifact: df"

    # Corrupt metadata JSON -> missing_metadata
    meta_path.write_text("{not-json", encoding="utf-8")
    hit, reason = cache.load("stage", "fp1", {}, ["df"])
    assert hit is False
    assert reason == "missing_metadata"


def test_atomic_save_cleans_tmp_on_error(tmp_path):
    cache = StageCache(tmp_path / "cache")
    with pytest.raises(TypeError, match="pandas DataFrame"):
        cache.save("bad_stage", "fp_err", {"bad": "not-a-df"}, ["bad"])
    stage_dir = tmp_path / "cache" / "bad_stage"
    leftovers = list(stage_dir.iterdir())
    assert leftovers == []


def test_retention_pruning_keeps_newest_prior_fingerprints(tmp_path):
    cache = StageCache(tmp_path / "cache", retain_prior_fingerprints=2)
    df = pd.DataFrame({"a": [1]})
    base = time.time() - 100
    for idx in range(4):
        fp = f"fp_{idx}"
        fp_dir = cache.save("prune_stage", fp, {"df": df}, ["df"])
        ts = base + idx * 10
        os.utime(fp_dir, (ts, ts))
    kept = sorted(p.name for p in (tmp_path / "cache" / "prune_stage").iterdir())
    assert kept == ["fp_1", "fp_2", "fp_3"]


def test_fingerprint_v2_components_and_diff_reason(tmp_path):
    source = tmp_path / "data.txt"
    source.write_text("v1", encoding="utf-8")
    fp_calc = CacheFingerprint()
    cfg = {
        "data": {"path": str(source)},
        "estimation": {"lag": 1},
        "output": {"reports_dir": "reports/r1"},
        "cache": {"retain_prior_fingerprints": 2},
    }
    upstream = {"panel": pd.DataFrame({"x": [1.0, 2.0]})}

    res1 = fp_calc.compute(SampleStageA(), cfg, None, upstream, ["panel"])
    assert res1.components["format_version"]
    assert str(source) in res1.sources

    # Changing output/cache blocks does NOT change fingerprint when cache_inputs is None
    cfg_out_changed = dict(cfg, output={"reports_dir": "reports/r2"}, cache={"retain_prior_fingerprints": 5})
    res_same = fp_calc.compute(SampleStageA(), cfg_out_changed, None, upstream, ["panel"])
    assert res_same.fingerprint == res1.fingerprint

    # Save first fingerprint to cache
    cache = StageCache(tmp_path / "cache")
    cache.save("est", res1.fingerprint, {"out": pd.DataFrame({"y": [1]})}, ["out"], component_hashes=res1.components)

    # Change config -> fingerprint_changed: config
    cfg_lag2 = {**cfg, "estimation": {"lag": 2}}
    res_cfg = fp_calc.compute(SampleStageA(), cfg_lag2, ["estimation.lag"], upstream, ["panel"])
    res_base_scoped = fp_calc.compute(SampleStageA(), cfg, ["estimation.lag"], upstream, ["panel"])
    assert res_cfg.fingerprint != res_base_scoped.fingerprint

    res_cfg_full = fp_calc.compute(SampleStageA(), cfg_lag2, None, upstream, ["panel"])
    hit, reason = cache.load("est", res_cfg_full.fingerprint, {}, ["out"], component_hashes=res_cfg_full.components)
    assert hit is False
    assert reason == "fingerprint_changed: config"

    # Change source file -> fingerprint_changed: sources
    source.write_text("v2", encoding="utf-8")
    res_src = fp_calc.compute(SampleStageA(), cfg, None, upstream, ["panel"])
    hit, reason = cache.load("est", res_src.fingerprint, {}, ["out"], component_hashes=res_src.components)
    assert hit is False
    assert reason == "fingerprint_changed: sources"

    # Change upstream DataFrame -> fingerprint_changed: upstream
    source.write_text("v1", encoding="utf-8")
    res_up = fp_calc.compute(SampleStageA(), cfg, None, {"panel": pd.DataFrame({"x": [1.0, 9.0]})}, ["panel"])
    hit, reason = cache.load("est", res_up.fingerprint, {}, ["out"], component_hashes=res_up.components)
    assert hit is False
    assert reason == "fingerprint_changed: upstream"

    # Change stage class source -> fingerprint_changed: stage_source
    res_code = fp_calc.compute(SampleStageB(), cfg, None, upstream, ["panel"])
    hit, reason = cache.load("est", res_code.fingerprint, {}, ["out"], component_hashes=res_code.components)
    assert hit is False
    assert reason == "fingerprint_changed: stage_source"


def test_dynamic_class_source_fallback():
    dyn_cls = type("DynamicStage", (), {"run": lambda self, data, config: data})
    res = CacheFingerprint().compute(dyn_cls(), {"a": 1}, ["a"], {}, [])
    assert len(res.fingerprint) == 16
    assert "stage_source" in res.components


def test_metadata_rejects_non_dataframe():
    with pytest.raises(TypeError):
        CacheArtifactMetadata.build({"not": "df"})
