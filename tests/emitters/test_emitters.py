import importlib
import json

import pandas as pd
import pytest

from reproducible_econ.emitters import (
    ClaimCheck,
    ClaimCheckStage,
    FigureStageBase,
    LatexMacroStage,
    LatexTableStage,
)
from reproducible_econ.emitters.tables import escape_latex
from reproducible_econ.pipeline.executor import StageExecutor


class SimpleLineFigureStage(FigureStageBase):
    def _plot(self, data, config, plt):
        fig, ax = plt.subplots()
        ax.plot([1, 2, 3], [2, 4, 6])
        self._save(fig, config, "line.png", data=data)


def test_latex_table_stage_booktabs_escaping_and_csv(tmp_path):
    df = pd.DataFrame(
        {
            "variable": ["unemp_gap%", "infl & core$"],
            "mean": [1.23456, 2.5],
            "n": [116, 120],
            "extra": ["drop_me", "drop_me"],
        }
    )
    cfg = {
        "output": {"reports_dir": str(tmp_path / "reports")},
        "tables": {
            "exports": [
                {
                    "key": "summary",
                    "filename": "summary.tex",
                    "caption": "Summary & Stats (100%)",
                    "label": "tab:summary",
                    "note": "Note: 5% level_test.",
                    "float_format": "%.2f",
                    "columns": ["variable", "mean", "n"],
                    "rename": {"variable": "Var_Name", "mean": "Mean", "n": "N"},
                    "also_csv": True,
                }
            ]
        },
    }
    executor = StageExecutor(cfg, "cfg.yaml")
    executor.run("tables", LatexTableStage(), {"summary": df}, cache=False)
    tex_path = tmp_path / "reports" / "tables" / "summary.tex"
    csv_path = tmp_path / "reports" / "tables" / "summary.csv"
    assert tex_path.is_file()
    assert csv_path.is_file()

    tex = tex_path.read_text(encoding="utf-8")
    assert r"\toprule" in tex
    assert r"\midrule" in tex
    assert r"\bottomrule" in tex
    assert r"\caption{Summary \& Stats (100\%)}" in tex
    assert r"\label{tab:summary}" in tex
    assert r"Var\_Name & Mean & N \\" in tex
    assert r"unemp\_gap\% & 1.23 & 116 \\" in tex
    assert r"infl \& core\$ & 2.50 & 120 \\" in tex
    assert "drop_me" not in tex
    assert "tables/summary.tex" in executor.manifest["outputs"]
    assert "tables/summary.csv" in executor.manifest["outputs"]


def test_latex_table_stage_missing_key_strict_and_escape():
    assert escape_latex(r"a_b & c% $d #e ~f ^g \h {i}") == r"a\_b \& c\% \$d \#e \textasciitilde{}f \textasciicircum{}g \textbackslash{}h \{i\}"
    with pytest.raises(KeyError, match="missing_df"):
        LatexTableStage().run({}, {"tables": {"exports": [{"key": "missing_df", "filename": "x.tex"}]}})


def test_latex_macro_stage_formats_digit_words_and_pval_floor(tmp_path):
    estimates = pd.DataFrame(
        [
            {"spec_name": "baseline_1", "key_variable": "u_gap", "coef": -0.45126, "se": 0.0512, "pval": 0.00012, "n_obs": 1200},
            {"spec_name": "alt", "key_variable": "u_gap", "coef": -0.31, "se": 0.08, "pval": 0.024, "n_obs": 116},
        ]
    )
    cfg = {
        "output": {"reports_dir": str(tmp_path / "reports")},
        "latex_macros": {
            "entries": [
                {"tidy_key": "estimates", "spec": "baseline_1", "key_variable": "u_gap", "name": "Spec_1"},
                {"tidy_key": "estimates", "spec": "alt", "key_variable": "u_gap", "name": "Alt"},
            ]
        },
    }
    executor = StageExecutor(cfg, "cfg.yaml")
    executor.run("macros", LatexMacroStage(), {"estimates": estimates}, cache=False)
    macros_path = tmp_path / "reports" / "macros.tex"
    content = macros_path.read_text(encoding="utf-8")
    assert "% Generated file. Do not hand edit." in content
    assert r"\newcommand{\SpecOneCoef}{-0.4513}" in content
    assert r"\newcommand{\SpecOneCoefShort}{-0.451}" in content
    assert r"\newcommand{\SpecOneSE}{0.0512}" in content
    assert r"\newcommand{\SpecOneSEShort}{0.051}" in content
    assert r"\newcommand{\SpecOneP}{<0.001}" in content
    assert r"\newcommand{\SpecOneN}{1,200}" in content
    assert r"\newcommand{\AltP}{0.024}" in content
    assert "macros.tex" in executor.manifest["outputs"]


def test_latex_macro_stage_loud_errors(tmp_path):
    base_cfg = {"output": {"reports_dir": str(tmp_path / "reports")}}
    stage = LatexMacroStage()

    with pytest.raises(ValueError, match="missing or empty"):
        stage.run({}, {**base_cfg, "latex_macros": {"entries": [{"tidy_key": "est", "spec": "s", "key_variable": "v", "name": "A"}]}})

    df = pd.DataFrame([{"spec_name": "s1", "key_variable": "x", "coef": 1.0, "se": 0.1, "pval": 0.01, "n_obs": 10}])
    with pytest.raises(ValueError, match="No row"):
        stage.run({"est": df}, {**base_cfg, "latex_macros": {"entries": [{"tidy_key": "est", "spec": "s2", "key_variable": "x", "name": "A"}]}})

    dup_df = pd.concat([df, df], ignore_index=True)
    with pytest.raises(ValueError, match="Ambiguous 2 rows"):
        stage.run({"est": dup_df}, {**base_cfg, "latex_macros": {"entries": [{"tidy_key": "est", "spec": "s1", "key_variable": "x", "name": "A"}]}})

    two_df = pd.DataFrame(
        [
            {"spec_name": "s1", "key_variable": "x", "coef": 1.0, "se": 0.1, "pval": 0.01, "n_obs": 10},
            {"spec_name": "s2", "key_variable": "x", "coef": 2.0, "se": 0.2, "pval": 0.02, "n_obs": 20},
        ]
    )
    with pytest.raises(ValueError, match="Macro stem collision"):
        stage.run(
            {"est": two_df},
            {
                **base_cfg,
                "latex_macros": {
                    "entries": [
                        {"tidy_key": "est", "spec": "s1", "key_variable": "x", "name": "Spec_1"},
                        {"tidy_key": "est", "spec": "s2", "key_variable": "x", "name": "SpecOne"},
                    ]
                },
            },
        )

    nan_df = pd.DataFrame([{"spec_name": "s1", "key_variable": "x", "coef": float("nan"), "se": 0.1, "pval": 0.01, "n_obs": 10}])
    with pytest.raises(ValueError, match="is NaN"):
        stage.run({"est": nan_df}, {**base_cfg, "latex_macros": {"entries": [{"tidy_key": "est", "spec": "s1", "key_variable": "x", "name": "A"}]}})


def test_figure_stage_missing_matplotlib_skip_and_error(tmp_path, monkeypatch):
    real_import = importlib.import_module

    def _block_mpl(name, *args, **kwargs):
        if name == "matplotlib" or name.startswith("matplotlib."):
            raise ImportError("No module named 'matplotlib'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", _block_mpl)
    stage = SimpleLineFigureStage()
    data = {"existing": 1}
    cfg_skip = {"output": {"reports_dir": str(tmp_path / "reports")}, "plotting": {"on_missing_matplotlib": "skip"}}
    result = stage.run(data, cfg_skip)
    assert result == {"existing": 1}
    assert not (tmp_path / "reports" / "figures" / "line.png").exists()

    cfg_err = {"output": {"reports_dir": str(tmp_path / "reports")}, "plotting": {"on_missing_matplotlib": "error"}}
    with pytest.raises(ImportError, match="reproducible-econ\\[figures\\]"):
        stage.run(data, cfg_err)


def test_figure_stage_emits_png_when_matplotlib_available(tmp_path):
    pytest.importorskip("matplotlib")
    cfg = {"output": {"reports_dir": str(tmp_path / "reports")}, "plotting": {"dpi": 100}}
    executor = StageExecutor(cfg, "cfg.yaml")
    executor.run("fig", SimpleLineFigureStage(), {}, cache=False)
    fig_path = tmp_path / "reports" / "figures" / "line.png"
    assert fig_path.is_file()
    assert fig_path.stat().st_size > 0
    assert "figures/line.png" in executor.manifest["outputs"]


def test_claim_check_assertions_and_stage(tmp_path):
    estimates = pd.DataFrame(
        [
            {
                "spec_name": "baseline",
                "key_variable": "u_gap",
                "coef": -0.45,
                "pval": 0.001,
                "n_obs": 116,
                "r2": 0.62,
                "date_min": "2015Q2",
                "date_max": "2022Q2",
            }
        ]
    )
    claims = [
        {
            "id": "slope_ok",
            "description": "Negative slope with expected magnitude and bounds",
            "tidy_key": "estimates",
            "spec": "baseline",
            "key_variable": "u_gap",
            "sign": "negative",
            "coef": -0.45,
            "tol": 0.01,
            "n_obs": 116,
            "pval_below": 0.05,
            "pval_above": 0.0,
            "pval_between": [0.0, 0.01],
            "date_min": "2015Q2",
            "date_max": "2022Q2",
            "bounds": {"r2": {"min": 0.5, "max": 0.9}},
        },
        {
            "id": "slope_wrong_sign",
            "tidy_key": "estimates",
            "spec": "baseline",
            "key_variable": "u_gap",
            "sign": "positive",
        },
        {
            "id": "missing_row",
            "tidy_key": "estimates",
            "spec": "nonexistent",
            "key_variable": "u_gap",
            "sign": "negative",
        },
    ]

    results, summary = ClaimCheck().verify(claims, {"estimates": estimates})
    assert summary == {"total": 3, "passed": 1, "failed": 1, "unresolved": 1}
    assert results[0]["status"] == "passed"
    assert results[1]["status"] == "failed"
    assert results[2]["status"] == "unresolved"

    # Default fail_on_error=False records report and manifest summary without raising
    cfg = {
        "output": {"reports_dir": str(tmp_path / "reports")},
        "claims": {"entries": claims},
    }
    executor = StageExecutor(cfg, "cfg.yaml")
    out_data = executor.run("claims", ClaimCheckStage(), {"estimates": estimates}, cache=False, produces=["claims_results"])
    report_path = tmp_path / "reports" / "claims_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["passed"] == 1
    assert executor.manifest["claims"]["failed"] == 1
    assert executor.manifest["claims"]["report_path"] == "claims_report.json"
    assert "claims_report.json" in executor.manifest["outputs"]
    assert list(out_data["claims_results"]["status"]) == ["passed", "failed", "unresolved"]

    # fail_on_error=True raises ValueError on failure
    cfg_strict = {
        "output": {"reports_dir": str(tmp_path / "reports_strict")},
        "claims": {"entries": claims, "fail_on_error": True},
    }
    with pytest.raises(ValueError, match="1 failed, 1 unresolved"):
        ClaimCheckStage().run({"estimates": estimates}, cfg_strict)


def test_claim_check_reports_observed_and_expected_values():
    estimates = pd.DataFrame(
        [{"spec_name": "baseline", "key_variable": "u_gap", "coef": -0.45, "pval": 0.001}]
    )
    claims = [
        {
            "id": "coef_ok",
            "tidy_key": "estimates",
            "spec": "baseline",
            "key_variable": "u_gap",
            "coef": -0.45,
            "tol": 0.01,
        },
        {
            "id": "coef_wrong",
            "tidy_key": "estimates",
            "spec": "baseline",
            "key_variable": "u_gap",
            "coef": 0.10,
            "tol": 0.05,
            "pval_below": 0.01,
        },
    ]
    results, summary = ClaimCheck().verify(claims, {"estimates": estimates})
    assert summary == {"total": 2, "passed": 1, "failed": 1, "unresolved": 0}

    ok = results[0]
    coef_check = ok["checks"][0]
    assert coef_check == {"condition": "coef", "observed": -0.45, "expected": -0.45, "tolerance": 0.01, "passed": True}

    bad = results[1]
    assert bad["status"] == "failed"
    assert {c["condition"] for c in bad["checks"]} == {"coef", "pval_below"}
    coef_check = next(c for c in bad["checks"] if c["condition"] == "coef")
    assert coef_check["observed"] == -0.45
    assert coef_check["expected"] == 0.10
    assert coef_check["tolerance"] == 0.05
    assert coef_check["passed"] is False
    pval_check = next(c for c in bad["checks"] if c["condition"] == "pval_below")
    assert pval_check["observed"] == 0.001
    assert pval_check["threshold"] == 0.01
    assert pval_check["passed"] is True


def test_emitter_up_to_date_skip_and_rerun_on_delete_or_modify(tmp_path):
    estimates = pd.DataFrame([{"spec_name": "s1", "key_variable": "x", "coef": -0.5, "se": 0.1, "pval": 0.001, "n_obs": 100}])
    cfg = {
        "output": {"cache_dir": str(tmp_path / "cache"), "reports_dir": str(tmp_path / "reports")},
        "latex_macros": {"entries": [{"tidy_key": "estimates", "spec": "s1", "key_variable": "x", "name": "Base"}]},
    }
    macros_path = tmp_path / "reports" / "macros.tex"

    first = StageExecutor(cfg, tmp_path / "cfg.yaml")
    first.run("export_macros", LatexMacroStage(), {"estimates": estimates}, cache=False, upstream_keys=["estimates"])
    assert first.manifest["stages"]["export_macros"]["status"] == "executed"
    assert macros_path.is_file()

    # Unchanged inputs + intact output -> up_to_date
    second = StageExecutor(cfg, tmp_path / "cfg.yaml")
    second.run("export_macros", LatexMacroStage(), {"estimates": estimates}, cache=False, upstream_keys=["estimates"])
    assert second.manifest["stages"]["export_macros"]["status"] == "up_to_date"
    assert second.manifest["stages"]["export_macros"]["elapsed_sec"] == 0.0
    assert "macros.tex" in second.manifest["outputs"]

    # Hand-modified output file -> re-executes with output_modified
    macros_path.write_text("% tampered\n", encoding="utf-8")
    third = StageExecutor(cfg, tmp_path / "cfg.yaml")
    third.run("export_macros", LatexMacroStage(), {"estimates": estimates}, cache=False, upstream_keys=["estimates"])
    assert third.manifest["stages"]["export_macros"]["status"] == "executed"
    assert third.manifest["stages"]["export_macros"]["cache_miss_reason"] == "output_modified: macros.tex"

    # Deleted output file -> re-executes with missing_output
    macros_path.unlink()
    fourth = StageExecutor(cfg, tmp_path / "cfg.yaml")
    fourth.run("export_macros", LatexMacroStage(), {"estimates": estimates}, cache=False, upstream_keys=["estimates"])
    assert fourth.manifest["stages"]["export_macros"]["status"] == "executed"
    assert fourth.manifest["stages"]["export_macros"]["cache_miss_reason"] == "missing_output: macros.tex"
    assert macros_path.is_file()
