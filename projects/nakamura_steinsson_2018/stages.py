import logging
from pathlib import Path

import pandas as pd
from stats_transformer.models import RobustOLSModel

from reproducible_econ.pipeline.stage import BaseStage

logger = logging.getLogger(__name__)


def _load_dated_parquet(path):
    frame = pd.read_parquet(Path(path)).reset_index()
    date_col = "date" if "date" in frame.columns else "Date"
    frame = frame.rename(columns={date_col: "date"})
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values("date").reset_index(drop=True)


class PrepareEventDataStage(BaseStage):
    """Build FOMC event-study panel of daily Treasury, TIPS, and breakeven yield changes."""

    def run(self, data, config):
        """Load yield and policy-news shock files, compute daily changes, and filter FOMC dates."""
        data_cfg = config.get("data") or {}
        nominal = _load_dated_parquet(data_cfg["nominal_yields_path"])
        real = _load_dated_parquet(data_cfg["real_yields_path"])
        fomc = _load_dated_parquet(data_cfg["fomc_meetings_path"])
        shocks = _load_dated_parquet(data_cfg["shocks_path"])
        maturities = list(data_cfg.get("maturities", ["02", "03", "05", "10"]))

        nom_cols = ["date"]
        for mat in maturities:
            col = f"sveny{mat}"
            dcol = f"d_sveny{mat}"
            nominal[dcol] = nominal[col].diff()
            nom_cols.append(dcol)

        real_cols = ["date"]
        for mat in maturities:
            col = f"tipsy{mat}"
            dcol = f"d_tipsy{mat}"
            real[dcol] = real[col].diff()
            real_cols.append(dcol)

        panel = shocks[["date", "ns", "gss_target", "gss_path"]].merge(nominal[nom_cols], on="date", how="inner")
        panel = panel.merge(real[real_cols], on="date", how="left")
        panel = panel.merge(fomc[["date", "unscheduled"]], on="date", how="left")
        panel["unscheduled"] = panel["unscheduled"].fillna(0).astype(int)

        for mat in maturities:
            panel[f"d_breakeven{mat}"] = panel[f"d_sveny{mat}"] - panel[f"d_tipsy{mat}"]

        start_date = pd.Timestamp(data_cfg.get("start_date", "2000-01-01"))
        end_date = pd.Timestamp(data_cfg.get("end_date", "2014-03-31"))
        panel = panel[(panel["date"] >= start_date) & (panel["date"] <= end_date)].copy()
        if bool(data_cfg.get("scheduled_only", True)):
            panel = panel[panel["unscheduled"] == 0].copy()

        crisis_start = data_cfg.get("exclude_crisis_start")
        crisis_end = data_cfg.get("exclude_crisis_end")
        if crisis_start and crisis_end:
            c_start = pd.Timestamp(crisis_start)
            c_end = pd.Timestamp(crisis_end)
            panel = panel[~((panel["date"] >= c_start) & (panel["date"] <= c_end))].copy()

        panel["date_str"] = panel["date"].dt.strftime("%Y-%m-%d")
        panel = panel.drop(columns=["date"]).reset_index(drop=True)

        summary_vars = ["ns", "d_sveny02", "d_tipsy02", "d_breakeven02", "d_sveny05", "d_tipsy05", "d_sveny10", "d_tipsy10"]
        summary_rows = []
        for var in summary_vars:
            if var not in panel.columns:
                continue
            series = panel[var].dropna()
            summary_rows.append(
                {
                    "variable": var,
                    "mean": float(series.mean()),
                    "std": float(series.std(ddof=1)),
                    "min": float(series.min()),
                    "max": float(series.max()),
                    "n": len(series),
                }
            )

        logger.info("Prepared FOMC event panel: %d meetings (%s to %s)", len(panel), panel["date_str"].min(), panel["date_str"].max())
        data["event_panel"] = panel
        data["summary_stats"] = pd.DataFrame(summary_rows)
        return data


class EstimateYieldResponseStage(BaseStage):
    """Estimate high-frequency yield-curve responses via RobustOLSModel."""

    def run(self, data, config):
        """Run robust OLS event-study regressions across nominal, real, and breakeven yields."""
        panel = data["event_panel"].copy()
        est_cfg = config.get("estimation") or {}
        shock_col = str(est_cfg.get("shock_column", "ns"))
        cov_type = str(est_cfg.get("cov_type", "HC1"))
        winsorize_pct = float(est_cfg.get("winsorize_pct", 0.0))
        specs = list(est_cfg.get("specs") or [])
        if not specs:
            raise ValueError("estimation.specs must declare at least one regression specification")

        rows = []
        for spec in specs:
            spec_name = spec["name"]
            dependent = spec["dependent"]
            sub = panel[["date_str", dependent, shock_col]].dropna().copy()
            if winsorize_pct > 0.0:
                for col in (dependent, shock_col):
                    low = sub[col].quantile(winsorize_pct)
                    high = sub[col].quantile(1.0 - winsorize_pct)
                    sub[col] = sub[col].clip(lower=low, upper=high)

            model = RobustOLSModel(target=dependent, independent_variables=[shock_col], cov_type=cov_type)
            metrics = model.fit(sub)
            res = model.results
            coef = float(res.params[shock_col])
            se = float(res.model.bse[shock_col])
            tstat = float(res.model.tvalues[shock_col])
            pval = float(res.pvalues[shock_col])
            rows.append(
                {
                    "spec_name": spec_name,
                    "outcome": spec.get("label", dependent),
                    "key_variable": shock_col,
                    "coef": coef,
                    "se": se,
                    "tstat": tstat,
                    "pval": pval,
                    "n_obs": int(metrics["num_observations"]),
                    "r2": float(metrics["r_squared"]),
                    "date_min": str(sub["date_str"].min()),
                    "date_max": str(sub["date_str"].max()),
                }
            )

        logger.info("Estimated %d yield-curve OLS specifications (%s SE)", len(rows), cov_type)
        data["estimates"] = pd.DataFrame(rows)
        return data
