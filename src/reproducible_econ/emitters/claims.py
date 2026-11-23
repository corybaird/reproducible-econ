import json
import logging
from pathlib import Path

import pandas as pd

from reproducible_econ.emitters import record_emitted_file
from reproducible_econ.pipeline.executor import CLAIMS_SUMMARY_KEY
from reproducible_econ.pipeline.stage import BaseStage

logger = logging.getLogger(__name__)


class ClaimCheck:
    """Verify declarative econometric claims against tidy DataFrames."""

    def __init__(self, spec_col="spec_name", var_col="key_variable", coef_col="coef", pval_col="pval", n_obs_col="n_obs", date_min_col="date_min", date_max_col="date_max", default_tol=0.001):
        self.spec_col = spec_col
        self.var_col = var_col
        self.coef_col = coef_col
        self.pval_col = pval_col
        self.n_obs_col = n_obs_col
        self.date_min_col = date_min_col
        self.date_max_col = date_max_col
        self.default_tol = float(default_tol)

    def verify(self, claims, data):
        """Evaluate a list of claim dicts against data; return (results, summary)."""
        results = [self._check_one(claim, data) for claim in claims]
        summary = {
            "total": len(results),
            "passed": sum(1 for item in results if item["status"] == "passed"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
            "unresolved": sum(1 for item in results if item["status"] == "unresolved"),
        }
        return results, summary

    def _check_one(self, claim, data):
        claim_id = claim["id"]
        description = claim.get("description", "")
        tidy_key = claim.get("tidy_key")
        if tidy_key not in data or not isinstance(data[tidy_key], pd.DataFrame) or data[tidy_key].empty:
            return self._record(claim_id, description, "unresolved", f"Artifact {tidy_key!r} is missing or empty")

        frame = data[tidy_key]
        mask = pd.Series(True, index=frame.index)
        if "spec" in claim and claim["spec"] is not None:
            if self.spec_col not in frame.columns:
                return self._record(claim_id, description, "unresolved", f"Missing column {self.spec_col!r}")
            mask &= frame[self.spec_col] == claim["spec"]
        if "key_variable" in claim and claim["key_variable"] is not None:
            if self.var_col not in frame.columns:
                return self._record(claim_id, description, "unresolved", f"Missing column {self.var_col!r}")
            mask &= frame[self.var_col] == claim["key_variable"]

        matched = frame[mask]
        if len(matched) == 0:
            return self._record(claim_id, description, "unresolved", "No matching row found")
        if len(matched) > 1:
            return self._record(claim_id, description, "unresolved", f"Ambiguous match ({len(matched)} rows)")
        row = matched.iloc[0]

        failures = []
        checks = []
        unresolved_reason = self._evaluate_assertions(claim, frame.columns, row, failures, checks)
        if unresolved_reason is not None:
            return self._record(claim_id, description, "unresolved", unresolved_reason)
        if failures:
            return self._record(claim_id, description, "failed", "; ".join(failures), failures=failures, checks=checks)
        return self._record(claim_id, description, "passed", "", checks=checks)

    def _evaluate_assertions(self, claim, columns, row, failures, checks):
        if "sign" in claim:
            val, err = self._numeric_field(columns, row, self.coef_col)
            if err:
                return err
            expected_sign = claim["sign"]
            if expected_sign == "positive" and not (val > 0):
                failures.append(f"sign expected positive, got {val:.6g}")
            elif expected_sign == "negative" and not (val < 0):
                failures.append(f"sign expected negative, got {val:.6g}")
            elif expected_sign not in ("positive", "negative"):
                return f"Unknown sign expectation {expected_sign!r}"
            checks.append({"condition": "sign", "observed": val, "expected": expected_sign, "passed": not failures})

        if "coef" in claim:
            val, err = self._numeric_field(columns, row, self.coef_col)
            if err:
                return err
            expected = float(claim["coef"])
            tol = float(claim.get("tol", self.default_tol))
            passed = abs(val - expected) <= tol
            if not passed:
                failures.append(f"coef expected {expected} +/- {tol}, got {val:.6g}")
            checks.append({"condition": "coef", "observed": val, "expected": expected, "tolerance": tol, "passed": passed})

        if "n_obs" in claim:
            val, err = self._numeric_field(columns, row, self.n_obs_col)
            if err:
                return err
            expected_n = int(claim["n_obs"])
            passed = round(val) == expected_n
            if not passed:
                failures.append(f"n_obs expected {expected_n}, got {round(val)}")
            checks.append({"condition": "n_obs", "observed": round(val), "expected": expected_n, "passed": passed})

        if "pval_below" in claim:
            val, err = self._numeric_field(columns, row, self.pval_col)
            if err:
                return err
            limit = float(claim["pval_below"])
            passed = val < limit
            if not passed:
                failures.append(f"pval expected < {limit}, got {val:.6g}")
            checks.append({"condition": "pval_below", "observed": val, "expected": f"< {limit}", "threshold": limit, "passed": passed})

        if "pval_above" in claim:
            val, err = self._numeric_field(columns, row, self.pval_col)
            if err:
                return err
            limit = float(claim["pval_above"])
            passed = val > limit
            if not passed:
                failures.append(f"pval expected > {limit}, got {val:.6g}")
            checks.append({"condition": "pval_above", "observed": val, "expected": f"> {limit}", "threshold": limit, "passed": passed})

        if "pval_between" in claim:
            val, err = self._numeric_field(columns, row, self.pval_col)
            if err:
                return err
            low, high = claim["pval_between"]
            passed = float(low) <= val <= float(high)
            if not passed:
                failures.append(f"pval expected in [{low}, {high}], got {val:.6g}")
            checks.append({"condition": "pval_between", "observed": val, "expected": f"in [{low}, {high}]", "passed": passed})

        if "date_min" in claim:
            val, err = self._raw_field(columns, row, self.date_min_col)
            if err:
                return err
            passed = str(val) == str(claim["date_min"])
            if not passed:
                failures.append(f"date_min expected {claim['date_min']!r}, got {val!r}")
            checks.append({"condition": "date_min", "observed": str(val), "expected": str(claim["date_min"]), "passed": passed})

        if "date_max" in claim:
            val, err = self._raw_field(columns, row, self.date_max_col)
            if err:
                return err
            passed = str(val) == str(claim["date_max"])
            if not passed:
                failures.append(f"date_max expected {claim['date_max']!r}, got {val!r}")
            checks.append({"condition": "date_max", "observed": str(val), "expected": str(claim["date_max"]), "passed": passed})

        for col_name, spec in (claim.get("bounds") or {}).items():
            val, err = self._numeric_field(columns, row, col_name)
            if err:
                return err
            passed = True
            if "min" in spec and val < float(spec["min"]):
                failures.append(f"{col_name} expected >= {spec['min']}, got {val:.6g}")
                passed = False
            if "max" in spec and val > float(spec["max"]):
                failures.append(f"{col_name} expected <= {spec['max']}, got {val:.6g}")
                passed = False
            checks.append({"condition": f"bounds:{col_name}", "observed": val, "expected": spec, "passed": passed})

        return None

    @staticmethod
    def _raw_field(columns, row, col_name):
        if col_name not in columns:
            return None, f"Missing column {col_name!r}"
        value = row[col_name]
        if pd.isna(value):
            return None, f"Column {col_name!r} is NaN"
        return value, None

    @classmethod
    def _numeric_field(cls, columns, row, col_name):
        value, err = cls._raw_field(columns, row, col_name)
        if err:
            return None, err
        return float(value), None

    @staticmethod
    def _record(claim_id, description, status, reason, failures=None, checks=None):
        return {
            "id": claim_id,
            "description": description,
            "status": status,
            "reason": reason,
            "failures": list(failures or []),
            "checks": list(checks or []),
        }


class ClaimCheckStage(BaseStage):
    """Run declarative claim checks, write claims_report.json, and record manifest summary."""

    def run(self, data, config):
        """Verify config['claims']['entries'], emit report, and optionally fail on errors."""
        claims_cfg = config.get("claims") or {}
        entries = claims_cfg.get("entries") or []
        fail_on_error = bool(claims_cfg.get("fail_on_error", False))
        checker = ClaimCheck(
            spec_col=claims_cfg.get("spec_col", "spec_name"),
            var_col=claims_cfg.get("var_col", "key_variable"),
            coef_col=claims_cfg.get("coef_col", "coef"),
            pval_col=claims_cfg.get("pval_col", "pval"),
            n_obs_col=claims_cfg.get("n_obs_col", "n_obs"),
            date_min_col=claims_cfg.get("date_min_col", "date_min"),
            date_max_col=claims_cfg.get("date_max_col", "date_max"),
            default_tol=claims_cfg.get("default_tol", 0.001),
        )
        results, summary = checker.verify(entries, data)

        for item in results:
            if item["status"] != "passed":
                logger.warning("Claim %s (%s): %s", item["id"], item["status"], item["reason"])

        output_cfg = config.get("output") or {}
        reports_dir = Path(output_cfg.get("reports_dir", "reports"))
        out_path = Path(output_cfg.get("claims_path") or (reports_dir / "claims_report.json"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"summary": summary, "claims": results}, indent=2), encoding="utf-8")
        record_emitted_file(data, out_path)
        logger.info("Wrote claims report: %s (%d/%d passed)", out_path, summary["passed"], summary["total"])

        try:
            report_rel = out_path.resolve().relative_to(reports_dir.resolve()).as_posix()
        except ValueError:
            report_rel = str(out_path)
        data[CLAIMS_SUMMARY_KEY] = {**summary, "report_path": report_rel}
        data["claims_results"] = pd.DataFrame(
            [{"id": r["id"], "status": r["status"], "description": r["description"], "reason": r["reason"]} for r in results],
            columns=["id", "status", "description", "reason"],
        )

        if fail_on_error and (summary["failed"] > 0 or summary["unresolved"] > 0):
            raise ValueError(f"Claim checks failed: {summary['failed']} failed, {summary['unresolved']} unresolved")
        return data
