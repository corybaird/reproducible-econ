import pytest

from reproducible_econ.config import ConfigLoader, get_nested, resolve_project_root


def test_load_single_yaml_and_builtins(tmp_path):
    cfg_file = tmp_path / "pipeline.yaml"
    cfg_file.write_text(
        "project:\n"
        "  name: demo\n"
        "  seed: 42\n"
        "output:\n"
        "  root: ${config_dir}/out\n"
        "  run_dir: ${output.root}/${run_timestamp}\n"
        "  seed_copy: ${project.seed}\n",
        encoding="utf-8",
    )
    loader = ConfigLoader(run_timestamp="20261120T010203Z")
    config = loader.load(cfg_file)
    assert config["project"]["name"] == "demo"
    assert config["output"]["root"] == f"{tmp_path.resolve()}/out"
    assert config["output"]["run_dir"] == f"{tmp_path.resolve()}/out/20261120T010203Z"
    assert config["output"]["seed_copy"] == 42
    assert loader.last_includes == []
    assert loader.last_run_timestamp == "20261120T010203Z"


def test_includes_merge_order_and_nested_includes(tmp_path):
    sub_dir = tmp_path / "parts"
    sub_dir.mkdir()
    (sub_dir / "base.yaml").write_text("project:\n  name: nested\n", encoding="utf-8")
    (sub_dir / "mid.yaml").write_text("includes:\n  - base.yaml\nestimation:\n  lag: 2\n", encoding="utf-8")
    root = tmp_path / "root.yaml"
    root.write_text(
        "includes:\n  - parts/mid.yaml\noutput:\n  label: ${project.name}_lag${estimation.lag}\n",
        encoding="utf-8",
    )
    loader = ConfigLoader()
    config = loader.load(root)
    assert config["project"]["name"] == "nested"
    assert config["estimation"]["lag"] == 2
    assert config["output"]["label"] == "nested_lag2"
    assert loader.last_includes == ["parts/mid.yaml", "parts/base.yaml"]


def test_duplicate_key_between_includes_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text("shared:\n  x: 1\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("shared:\n  x: 2\n", encoding="utf-8")
    root = tmp_path / "root.yaml"
    root.write_text("includes:\n  - a.yaml\n  - b.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate top-level config keys"):
        ConfigLoader().load(root)


def test_duplicate_key_between_include_and_root_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text("project:\n  name: a\n", encoding="utf-8")
    root = tmp_path / "root.yaml"
    root.write_text("includes:\n  - a.yaml\nproject:\n  name: root\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate top-level config keys"):
        ConfigLoader().load(root)


def test_circular_include_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text("includes:\n  - b.yaml\na: 1\n", encoding="utf-8")
    (tmp_path / "b.yaml").write_text("includes:\n  - a.yaml\nb: 2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Circular config include"):
        ConfigLoader().load(tmp_path / "a.yaml")


def test_unresolved_variable_rejected(tmp_path):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text("output:\n  path: ${missing.key}/file\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unresolved config variable"):
        ConfigLoader().load(cfg)


def test_circular_interpolation_rejected(tmp_path):
    cfg = tmp_path / "cycle.yaml"
    cfg.write_text("a: ${b}\nb: ${a}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Circular variable interpolation"):
        ConfigLoader().load(cfg)


def test_self_interpolation_rejected(tmp_path):
    cfg = tmp_path / "self.yaml"
    cfg.write_text("a: prefix_${a}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Circular variable interpolation"):
        ConfigLoader().load(cfg)


def test_diamond_interpolation_allowed(tmp_path):
    cfg = tmp_path / "diamond.yaml"
    cfg.write_text("base: reports\na: ${base}/tables\nb: ${base}/figures\n", encoding="utf-8")
    loaded = ConfigLoader().load(cfg)
    assert loaded["a"] == "reports/tables"
    assert loaded["b"] == "reports/figures"


def test_missing_file_and_non_mapping_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        ConfigLoader().load(tmp_path / "nope.yaml")
    bad = tmp_path / "list.yaml"
    bad.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(TypeError, match="YAML mapping"):
        ConfigLoader().load(bad)


def test_get_nested_helper():
    data = {"a": {"b": {"c": 7}}}
    assert get_nested(data, "a.b.c") == 7
    assert get_nested(data, "a.missing", default=None) is None
    with pytest.raises(KeyError):
        get_nested(data, "a.missing")


def test_relative_paths_resolve_against_project_root_not_cwd(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    cfg_dir = repo / "references" / "configs"
    cfg_dir.mkdir(parents=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    abs_target = (tmp_path / "external_abs").resolve()
    cfg = cfg_dir / "pipeline.yaml"
    cfg.write_text(
        f"output:\n"
        f"  cache_dir: .cache/demo\n"
        f"  reports_dir: reports/demo\n"
        f"  tables_dir: ${{output.reports_dir}}/tables\n"
        f"  macros_path: ${{output.reports_dir}}/macros.tex\n"
        f"  external_dir: {abs_target}\n"
        f"latex_macros:\n"
        f"  output_path: ${{output.macros_path}}\n",
        encoding="utf-8",
    )
    other_cwd = tmp_path / "other_cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    loader = ConfigLoader()
    loaded = loader.load(cfg)
    assert resolve_project_root(cfg) == repo.resolve()
    assert loaded["output"]["cache_dir"] == str((repo / ".cache/demo").resolve())
    assert loaded["output"]["reports_dir"] == str((repo / "reports/demo").resolve())
    assert loaded["output"]["tables_dir"] == str((repo / "reports/demo/tables").resolve())
    assert loaded["output"]["macros_path"] == str((repo / "reports/demo/macros.tex").resolve())
    assert loaded["latex_macros"]["output_path"] == str((repo / "reports/demo/macros.tex").resolve())
    assert loaded["output"]["external_dir"] == str(abs_target)


def test_relative_paths_fallback_to_config_dir_without_pyproject(tmp_path, monkeypatch):
    standalone = tmp_path / "standalone"
    standalone.mkdir()
    cfg = standalone / "pipe.yaml"
    cfg.write_text("output:\n  cache_dir: .cache/s\n  reports_dir: reports/s\n", encoding="utf-8")
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    loaded = ConfigLoader().load(cfg)
    assert resolve_project_root(cfg) == standalone.resolve()
    assert loaded["output"]["cache_dir"] == str((standalone / ".cache/s").resolve())
    assert loaded["output"]["reports_dir"] == str((standalone / "reports/s").resolve())
