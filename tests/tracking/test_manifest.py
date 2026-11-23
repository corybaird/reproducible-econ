import json
import subprocess

import pandas as pd

from reproducible_econ.tracking.manifest import RunManifest, summarize_artifact


def test_manifest_schema_public_deps_and_inventories(tmp_path):
    input_file = tmp_path / "source.csv"
    input_file.write_text("a,b\n1,2\n", encoding="utf-8")
    reports_dir = tmp_path / "reports"
    tables_dir = reports_dir / "tables"
    tables_dir.mkdir(parents=True)
    out_file = tables_dir / "tab1.tex"
    out_file.write_text("\\begin{table}\\end{table}\n", encoding="utf-8")

    cfg = {"project": {"name": "demo"}, "manifest": {"extra_packages": ["pytest"]}}
    manifest = RunManifest(cfg, "pipeline.yaml", no_cache=False, config_includes=["base.yaml"], targets=["est"], run_timestamp="20261120T010203Z")
    manifest.record_input(str(input_file))
    label = manifest.record_output(out_file, "export_tables", reports_dir=reports_dir)
    manifest.record_stage(
        "est",
        status="executed",
        elapsed_sec=0.1234567,
        phase="estimate",
        class_path="pkg.EstStage",
        fingerprint="abcdef0123456789",
        cache_miss_reason="no_cache",
        requires=["panel"],
        produces=["estimates"],
        output_artifacts={"estimates": summarize_artifact(pd.DataFrame({"c": [1.0]}))},
        emitted_files=[label],
    )
    manifest.record_claims({"total": 1, "passed": 1, "failed": 0, "unresolved": 0, "report_path": "claims_report.json"})

    saved = manifest.save(reports_dir, timestamped_copy=True)
    assert saved == reports_dir / "run_manifest.json"
    ts_copy = reports_dir / "run_manifest_20261120T010203Z.json"
    assert ts_copy.is_file()

    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["manifest_version"] == "2"
    assert payload["config_includes"] == ["base.yaml"]
    assert payload["targets"] == ["est"]
    assert payload["stage_timings_sec"]["est"] == 0.123457
    assert payload["stages"]["est"]["status"] == "executed"
    assert payload["stages"]["est"]["output_artifacts"]["estimates"]["rows"] == 1
    assert str(input_file) in payload["inputs"]
    assert payload["inputs"][str(input_file)]["bytes"] == input_file.stat().st_size
    assert "tables/tab1.tex" in payload["outputs"]
    assert payload["outputs"]["tables/tab1.tex"]["stage"] == "export_tables"
    assert payload["claims"]["passed"] == 1

    deps = payload["dependencies"]
    assert {"pandas", "pyarrow", "pyyaml", "reproducible-econ", "matplotlib", "pytest"} <= set(deps)
    for private_name in ("openai", "anthropic", "transformers", "torch"):
        assert private_name not in deps


def test_git_missing_and_timeout_fallbacks(monkeypatch):
    def _raise_missing(*args, **kwargs):
        raise FileNotFoundError("git not installed")

    monkeypatch.setattr(subprocess, "run", _raise_missing)
    m_missing = RunManifest({}, "cfg.yaml")
    assert m_missing.data["git_sha"] is None
    assert m_missing.data["git_dirty"] is None

    def _raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=5)

    monkeypatch.setattr(subprocess, "run", _raise_timeout)
    m_timeout = RunManifest({}, "cfg.yaml")
    assert m_timeout.data["git_sha"] is None
    assert m_timeout.data["git_dirty"] is None


def test_git_dirty_detects_staged_changes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    tracked = repo / "file.txt"
    tracked.write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    clean = RunManifest({}, "cfg.yaml", git_cwd=repo)
    assert clean.data["git_sha"] is not None
    assert clean.data["git_dirty"] is False

    # Stage a modification (git diff --quiet is 0, but git diff --cached --quiet is 1)
    tracked.write_text("v2\n", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    staged = RunManifest({}, "cfg.yaml", git_cwd=repo)
    assert staged.data["git_dirty"] is True
