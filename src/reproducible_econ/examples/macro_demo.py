import math

import numpy as np
import pandas as pd

from reproducible_econ.emitters.figures import FigureStageBase
from reproducible_econ.pipeline.stage import BaseStage


class PrepareMacroDataStage(BaseStage):
    """Generate a deterministic synthetic quarterly macro panel from config seed."""

    def run(self, data, config):
        """Build synthetic Phillips curve panel and summary statistics DataFrames."""
        seed = int((config.get("project") or {}).get("seed", 42))
        data_cfg = config.get("data") or {}
        economies = list(data_cfg.get("economies", ["ECON_A", "ECON_B", "ECON_C", "ECON_D"]))
        n_quarters = int(data_cfg.get("n_quarters", 30))
        start_year = int(data_cfg.get("start_year", 2015))
        start_quarter = str(data_cfg.get("start_quarter", "2015Q1"))
        end_quarter = str(data_cfg.get("end_quarter", "2022Q2"))
        lag_periods = int(data_cfg.get("lag_periods", 1))
        dgp = data_cfg.get("dgp") or {}
        intercept = float(dgp.get("intercept", 2.0))
        slope_unemp = float(dgp.get("slope_unemp", -0.45))
        persistence = float(dgp.get("persistence", 0.55))
        noise_std = float(dgp.get("noise_std", 0.25))

        quarters = [f"{start_year + (q // 4)}Q{(q % 4) + 1}" for q in range(n_quarters)]
        rng = np.random.default_rng(seed)

        rows = []
        for economy in economies:
            u_gap = np.zeros(n_quarters, dtype=float)
            inflation = np.zeros(n_quarters, dtype=float)
            inflation[0] = intercept / max(1.0 - persistence, 0.1) + rng.normal(0.0, noise_std)
            u_gap[0] = rng.normal(0.0, 1.0)
            for idx in range(1, n_quarters):
                u_gap[idx] = 0.7 * u_gap[idx - 1] + rng.normal(0.0, 1.0)
                inflation[idx] = intercept + slope_unemp * u_gap[idx] + persistence * inflation[idx - 1] + rng.normal(0.0, noise_std)
            for idx, quarter in enumerate(quarters):
                rows.append(
                    {
                        "economy": economy,
                        "quarter": quarter,
                        "unemployment_gap": round(float(u_gap[idx]), 6),
                        "inflation": round(float(inflation[idx]), 6),
                    }
                )

        panel = pd.DataFrame(rows)
        panel["lag_inflation"] = panel.groupby("economy")["inflation"].shift(lag_periods)
        panel = panel[(panel["quarter"] >= start_quarter) & (panel["quarter"] <= end_quarter)]
        panel = panel.dropna(subset=["lag_inflation"]).reset_index(drop=True)

        summary_rows = []
        for variable in ("inflation", "unemployment_gap", "lag_inflation"):
            series = panel[variable]
            summary_rows.append(
                {
                    "variable": variable,
                    "mean": float(series.mean()),
                    "std": float(series.std(ddof=1)),
                    "min": float(series.min()),
                    "max": float(series.max()),
                    "n": len(series),
                }
            )

        data["panel"] = panel
        data["summary_stats"] = pd.DataFrame(summary_rows)
        return data


class EstimatePhillipsStage(BaseStage):
    """Estimate OLS Phillips curve specifications with optional winsorization."""

    def run(self, data, config):
        """Run declared OLS specs via numpy and emit a tidy estimates DataFrame."""
        panel = data["panel"].copy()
        est_cfg = config.get("estimation") or {}
        winsorize_pct = float(est_cfg.get("winsorize_pct", 0.0))
        if winsorize_pct > 0.0:
            for col in ("inflation", "unemployment_gap", "lag_inflation"):
                if col in panel.columns:
                    low = panel[col].quantile(winsorize_pct)
                    high = panel[col].quantile(1.0 - winsorize_pct)
                    panel[col] = panel[col].clip(lower=low, upper=high)

        date_min = str(panel["quarter"].min())
        date_max = str(panel["quarter"].max())
        specs = est_cfg.get("specs") or [
            {"name": "baseline_ols", "dependent": "inflation", "regressors": ["unemployment_gap", "lag_inflation"]},
            {"name": "univariate_ols", "dependent": "inflation", "regressors": ["unemployment_gap"]},
        ]

        rows = []
        for spec in specs:
            spec_name = spec["name"]
            dependent = spec.get("dependent", "inflation")
            regressors = list(spec["regressors"])
            y = panel[dependent].to_numpy(dtype=float)
            x_vars = panel[regressors].to_numpy(dtype=float)
            n_obs = len(y)
            design = np.column_stack([np.ones(n_obs, dtype=float), x_vars])
            beta, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
            resid = y - design @ beta
            dof = n_obs - design.shape[1]
            sigma2 = float(resid @ resid) / dof
            cov = sigma2 * np.linalg.inv(design.T @ design)
            se_vec = np.sqrt(np.diag(cov))
            tss = float(np.sum((y - y.mean()) ** 2))
            r2 = 1.0 - float(resid @ resid) / tss if tss > 0 else 0.0

            for idx, reg_name in enumerate(regressors, start=1):
                coef = float(beta[idx])
                se = float(se_vec[idx])
                tstat = coef / se if se > 0 else float("inf")
                pval = math.erfc(abs(tstat) / math.sqrt(2.0))
                rows.append(
                    {
                        "spec_name": spec_name,
                        "key_variable": reg_name,
                        "coef": coef,
                        "se": se,
                        "tstat": tstat,
                        "pval": pval,
                        "n_obs": n_obs,
                        "r2": r2,
                        "date_min": date_min,
                        "date_max": date_max,
                    }
                )

        data["estimates"] = pd.DataFrame(rows)
        return data


class PhillipsFigureStage(FigureStageBase):
    """Plot synthetic Phillips curve scatter with OLS fitted line."""

    def _plot(self, data, config, plt):
        panel = data["panel"]
        estimates = data["estimates"]

        fig, ax = plt.subplots(figsize=(6.5, 4.5))
        for economy, group in panel.groupby("economy"):
            ax.scatter(group["unemployment_gap"], group["inflation"], alpha=0.75, label=economy)

        x_vals = panel["unemployment_gap"].to_numpy(dtype=float)
        y_vals = panel["inflation"].to_numpy(dtype=float)
        slope, intercept = np.polyfit(x_vals, y_vals, 1)
        x_grid = np.linspace(float(x_vals.min()), float(x_vals.max()), 100)
        ax.plot(x_grid, intercept + slope * x_grid, color="black", linewidth=1.8, label="Univariate OLS fit")

        base_row = estimates[(estimates["spec_name"] == "baseline_ols") & (estimates["key_variable"] == "unemployment_gap")]
        if not base_row.empty:
            beta = float(base_row.iloc[0]["coef"])
            pval = float(base_row.iloc[0]["pval"])
            p_text = "<0.001" if pval < 0.001 else f"{pval:.3f}"
            ax.annotate(
                f"Baseline slope = {beta:.3f} (p {p_text})",
                xy=(0.04, 0.92),
                xycoords="axes fraction",
                fontsize=9,
                bbox={"boxstyle": "round,pad=0.3", "facecolor": "white", "alpha": 0.85},
            )

        ax.set_xlabel("Unemployment Gap (pp)")
        ax.set_ylabel("Inflation (%)")
        ax.set_title("Synthetic Phillips Curve")
        ax.grid(True, linestyle="--", alpha=0.35)
        ax.legend(frameon=True, fontsize=8)
        self._save(fig, config, "phillips_scatter.png", data=data)
