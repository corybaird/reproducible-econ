import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd
from stats_transformer.models import (
    LocalProjectionsIVModel,
    LocalProjectionsModel,
    PCAModel,
    ProxySVARModel,
    RobustOLSModel,
)

from reproducible_econ.emitters.figures import FigureStageBase
from reproducible_econ.pipeline.stage import BaseStage

logger = logging.getLogger(__name__)


def _load_dated_parquet(path):
    frame = pd.read_parquet(Path(path)).reset_index()
    date_col = "date" if "date" in frame.columns else "Date"
    frame = frame.rename(columns={date_col: "date"})
    frame["date"] = pd.to_datetime(frame["date"])
    return frame.sort_values("date").reset_index(drop=True)


class PrepareMacroDataStage(BaseStage):
    """Load FRBSF FOMC and monthly macro panels and compute log-level transformations."""

    def run(self, data, config):
        """Prepare FOMC event data, monthly macro panel, and summary statistics."""
        data_cfg = config.get("data") or {}
        fomc = _load_dated_parquet(data_cfg["fomc_path"])
        monthly = _load_dated_parquet(data_cfg["monthly_path"])
        monthly = monthly.rename(columns={"2y_treas": "treas_2y"})

        monthly["log_ip"] = 100.0 * np.log(monthly["ip"].astype(float))
        monthly["log_cpi"] = 100.0 * np.log(monthly["cpi"].astype(float))
        monthly["log_pcomm"] = 100.0 * np.log(monthly["crb_pcomm"].astype(float))
        monthly["lag_ebp"] = monthly["ebp"].shift(1)
        monthly["lag_cpi_yoy"] = monthly["log_cpi"].diff(12).shift(1)

        start_date = pd.Timestamp(data_cfg.get("start_date", "1988-02-01"))
        end_date = pd.Timestamp(data_cfg.get("end_date", "2019-12-01"))
        monthly = monthly[(monthly["date"] >= start_date) & (monthly["date"] <= end_date)].copy()
        required = ["treas_2y", "log_ip", "log_cpi", "unemp", "ebp", "mps", "mps_orth"]
        monthly = monthly.dropna(subset=required).copy()

        fomc = fomc[(fomc["date"] >= start_date) & (fomc["date"] <= end_date + pd.Timedelta(days=31))].copy()
        fomc["date_str"] = fomc["date"].dt.strftime("%Y-%m-%d")
        fomc["month_str"] = fomc["date"].dt.to_period("M").dt.to_timestamp().dt.strftime("%Y-%m-%d")
        fomc = fomc.drop(columns=["date"]).reset_index(drop=True)

        monthly["date_str"] = monthly["date"].dt.strftime("%Y-%m-%d")
        monthly = monthly.drop(columns=["date"]).reset_index(drop=True)

        summary_rows = []
        for var in required:
            series = monthly[var].dropna()
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

        logger.info(
            "Prepared FRBSF macro panel: %d months (%s to %s) and %d FOMC events",
            len(monthly),
            monthly["date_str"].min(),
            monthly["date_str"].max(),
            len(fomc),
        )
        data["fomc_panel"] = fomc
        data["monthly_panel"] = monthly
        data["summary_stats"] = pd.DataFrame(summary_rows)
        return data


class AlignAndTestShocksStage(BaseStage):
    """Construct PCA monetary-policy surprise factor and test pre-announcement predictability."""

    def run(self, data, config):
        """Aggregate FOMC Eurodollar PCA shocks to monthly frequency and run Table 1 OLS checks."""
        fomc = data["fomc_panel"].copy()
        monthly = data["monthly_panel"].copy()
        shock_cfg = config.get("shocks") or {}
        ed_cols = list(shock_cfg.get("eurodollar_columns", ["ed1", "ed2", "ed3", "ed4"]))
        cov_type = str(shock_cfg.get("cov_type", "HC1"))
        predictors = list(shock_cfg.get("predictors", ["nfp_surp", "nfp_12m"]))
        out_of_set_predictors = list(shock_cfg.get("out_of_set_predictors", ["lag_ebp", "lag_cpi_yoy"]))

        fomc_valid = fomc.dropna(subset=ed_cols).copy().reset_index(drop=True)
        pca = PCAModel(features=ed_cols, n_components=1, standardize=True)
        pca_metrics = pca.fit(fomc_valid[ed_cols])
        pc1 = np.asarray(pca.transformed_X, dtype=float)[:, 0]
        if float(np.corrcoef(pc1, fomc_valid[ed_cols[-1]].to_numpy(dtype=float))[0, 1]) < 0.0:
            pc1 = -pc1
        fomc_valid["mps_pca_event"] = pc1

        monthly_pca = fomc_valid.groupby("month_str", as_index=False)["mps_pca_event"].sum()
        monthly_pca = monthly_pca.rename(columns={"month_str": "date_str", "mps_pca_event": "mps_pca"})
        aligned = monthly.merge(monthly_pca, on="date_str", how="left")
        aligned["mps_pca"] = aligned["mps_pca"].fillna(0.0)

        corr_pca_mps = float(aligned["mps_pca"].corr(aligned["mps"]))
        corr_orth_mps = float(aligned["mps_orth"].corr(aligned["mps"]))
        explained = float(pca_metrics["explained_variance_ratio"][0])
        logger.info("PCA PC1 explains %.1f%% variance; corr(mps_pca, mps)=%.4f, corr(mps_orth, mps)=%.4f", 100.0 * explained, corr_pca_mps, corr_orth_mps)

        reg_specs = [
            ("raw_mps", "mps", predictors, 1.0),
            ("pca_mps", "mps_pca", predictors, corr_pca_mps),
            ("raw_mps_outset", "mps", out_of_set_predictors, 1.0),
            ("orth_mps_outset", "mps_orth", out_of_set_predictors, corr_orth_mps),
        ]

        rows = []
        for spec_name, dep_col, rhs_vars, corr_val in reg_specs:
            pred_df = aligned.dropna(subset=[dep_col, *rhs_vars]).copy()
            date_min = str(pred_df["date_str"].min())
            date_max = str(pred_df["date_str"].max())
            model = RobustOLSModel(target=dep_col, independent_variables=rhs_vars, cov_type=cov_type)
            metrics = model.fit(pred_df)
            res = model.results
            for var in rhs_vars:
                rows.append(
                    {
                        "spec_name": spec_name,
                        "shock_series": dep_col,
                        "key_variable": var,
                        "coef": float(res.params[var]),
                        "se": float(res.model.bse[var]),
                        "tstat": float(res.model.tvalues[var]),
                        "pval": float(res.pvalues[var]),
                        "n_obs": int(metrics["num_observations"]),
                        "r2": float(metrics["r_squared"]),
                        "f_pval": float(metrics["f_pvalue"]),
                        "corr_with_mps": corr_val,
                        "date_min": date_min,
                        "date_max": date_max,
                    }
                )

        data["aligned_panel"] = aligned
        data["shock_predictability"] = pd.DataFrame(rows)
        return data


class EstimateLocalProjectionsStage(BaseStage):
    """Estimate Jordà local projections across orthogonalized, raw, and robustness specs."""

    def run(self, data, config):
        """Run LocalProjectionsModel over configured horizons, outcomes, and lag lengths."""
        panel = data["aligned_panel"].copy()
        lp_cfg = config.get("lp") or {}
        horizon = int(lp_cfg.get("horizon", 24))
        baseline_lags = int(lp_cfg.get("baseline_lags", 6))
        robustness_lags = int(lp_cfg.get("robustness_lags", 12))
        cov_type = str(lp_cfg.get("cov_type", "HAC"))
        outcomes = list(lp_cfg.get("outcomes", ["treas_2y", "log_ip", "log_cpi", "unemp", "ebp"]))
        control_pool = list(lp_cfg.get("control_pool", ["treas_2y", "log_ip", "log_cpi", "unemp", "ebp"]))
        headline_horizons = [int(h) for h in lp_cfg.get("headline_horizons", [12, 24])]
        date_min = str(panel["date_str"].min())
        date_max = str(panel["date_str"].max())

        specs = [
            ("lp_orth", "mps_orth", baseline_lags),
            ("lp_raw", "mps", baseline_lags),
            ("lp_orth_robust", "mps_orth", robustness_lags),
        ]

        irf_rows = []
        headline_rows = []
        for spec_name, shock_var, lags in specs:
            for outcome in outcomes:
                controls = [col for col in control_pool if col != outcome]
                model = LocalProjectionsModel(
                    target=outcome,
                    shock_var=shock_var,
                    horizon=horizon,
                    controls=controls,
                    lags=lags,
                    cov_type=cov_type,
                )
                model.fit(panel)
                for entry in model.irf_results:
                    h = int(entry["horizon"])
                    coef = float(entry["effect"])
                    se = float(entry["stderr"])
                    pval = float(entry["pvalue"])
                    n_obs = len(panel) - lags - h
                    irf_rows.append(
                        {
                            "spec_name": spec_name,
                            "shock_var": shock_var,
                            "lags": lags,
                            "outcome": outcome,
                            "horizon": h,
                            "coef": coef,
                            "se": se,
                            "lower_ci": float(entry["lower_ci"]),
                            "upper_ci": float(entry["upper_ci"]),
                            "pval": pval,
                            "n_obs": n_obs,
                        }
                    )
                    if h in headline_horizons:
                        headline_rows.append(
                            {
                                "spec_name": f"{spec_name}_h{h}",
                                "model": spec_name,
                                "key_variable": outcome,
                                "horizon": h,
                                "lags": lags,
                                "coef": coef,
                                "se": se,
                                "pval": pval,
                                "n_obs": n_obs,
                                "date_min": date_min,
                                "date_max": date_max,
                            }
                        )

        logger.info("Estimated local projections: %d horizon rows across %d specs", len(irf_rows), len(specs))
        data["lp_irfs"] = pd.DataFrame(irf_rows)
        data["lp_headline"] = pd.DataFrame(headline_rows)
        return data


class EstimateStructuralModelsStage(BaseStage):
    """Estimate Proxy-SVAR and LP-IV structural responses normalized to a +25 bp rate shock."""

    def run(self, data, config):
        """Fit ProxySVARModel and LocalProjectionsIVModel and emit tidy model comparison."""
        panel = data["aligned_panel"].copy()
        s_cfg = config.get("structural") or {}
        horizon = int(s_cfg.get("horizon", 24))
        svar_lags = int(s_cfg.get("svar_lags", 6))
        svar_robust_lags = int(s_cfg.get("svar_robust_lags", 12))
        lpiv_lags = int(s_cfg.get("lpiv_lags", 6))
        lpiv_cov = str(s_cfg.get("lpiv_cov_type", "robust"))
        impact_pp = float(s_cfg.get("impact_bp", 25.0)) / 100.0
        endog = list(s_cfg.get("endog_variables", ["treas_2y", "log_ip", "log_cpi", "unemp", "ebp"]))
        policy_var = str(s_cfg.get("policy_variable", endog[0]))
        lpiv_outcomes = list(s_cfg.get("lpiv_outcomes", [col for col in endog if col != policy_var]))
        headline_horizons = [int(h) for h in s_cfg.get("headline_horizons", [12, 24])]
        date_min = str(panel["date_str"].min())
        date_max = str(panel["date_str"].max())

        irf_rows = []
        comp_rows = []

        psvar_specs = [
            ("psvar_orth", "mps_orth", svar_lags),
            ("psvar_raw", "mps", svar_lags),
            ("psvar_orth_robust", "mps_orth", svar_robust_lags),
        ]
        for spec_name, instrument, lags in psvar_specs:
            model = ProxySVARModel(target_variables=endog, instrument_variable=instrument, maxlags=lags)
            metrics = model.fit(panel)
            n_obs = int(metrics["nobs"])
            raw_irf = model.irf(horizons=horizon + 1)
            impact = float(raw_irf.loc[0, policy_var])
            scale = impact_pp / impact
            scaled = raw_irf * scale
            for h in range(horizon + 1):
                for outcome in endog:
                    coef = float(scaled.loc[h, outcome])
                    irf_rows.append(
                        {
                            "spec_name": spec_name,
                            "outcome": outcome,
                            "horizon": h,
                            "coef": coef,
                            "se": float("nan"),
                            "pval": float("nan"),
                            "n_obs": n_obs,
                        }
                    )
                    if h in headline_horizons:
                        comp_rows.append(
                            {
                                "spec_name": f"{spec_name}_h{h}",
                                "model": spec_name,
                                "key_variable": outcome,
                                "horizon": h,
                                "coef": coef,
                                "se": float("nan"),
                                "pval": float("nan"),
                                "n_obs": n_obs,
                                "date_min": date_min,
                                "date_max": date_max,
                            }
                        )

        for outcome in lpiv_outcomes:
            controls = [col for col in lpiv_outcomes if col != outcome]
            lpiv = LocalProjectionsIVModel(
                target_variable=outcome,
                shock_variable=policy_var,
                instrument_variable="mps_orth",
                control_variables=controls,
                horizons=horizon,
                lags=lpiv_lags,
                cov_type=lpiv_cov,
            )
            lpiv.fit(panel)
            coefs = np.asarray(lpiv.irf_coefficients, dtype=float) * impact_pp
            ses = np.asarray(lpiv.irf_std_errors, dtype=float) * impact_pp
            for h in range(horizon + 1):
                coef = float(coefs[h])
                se = float(ses[h])
                tstat = coef / se if se > 0.0 else float("inf")
                pval = float(math.erfc(abs(tstat) / math.sqrt(2.0)))
                n_obs = len(panel) - lpiv_lags - h
                irf_rows.append(
                    {
                        "spec_name": "lpiv_orth",
                        "outcome": outcome,
                        "horizon": h,
                        "coef": coef,
                        "se": se,
                        "pval": pval,
                        "n_obs": n_obs,
                    }
                )
                if h in headline_horizons:
                    comp_rows.append(
                        {
                            "spec_name": f"lpiv_orth_h{h}",
                            "model": "lpiv_orth",
                            "key_variable": outcome,
                            "horizon": h,
                            "coef": coef,
                            "se": se,
                            "pval": pval,
                            "n_obs": n_obs,
                            "date_min": date_min,
                            "date_max": date_max,
                        }
                    )

        logger.info("Estimated Proxy-SVAR (%d specs) and LP-IV (%d outcomes)", len(psvar_specs), len(lpiv_outcomes))
        data["structural_irfs"] = pd.DataFrame(irf_rows)
        data["model_comparison"] = pd.DataFrame(comp_rows)
        return data


class MonetaryIRFFigureStage(FigureStageBase):
    """Plot LP orthogonalized-vs-raw IRFs and Proxy-SVAR / LP-IV structural IRFs."""

    def _plot(self, data, config, plt):
        lp_irfs = data["lp_irfs"]
        struct_irfs = data["structural_irfs"]
        impact_bp = round(float((config.get("structural") or {}).get("impact_bp", 25.0)))
        panels = [
            ("log_ip", "Industrial Production", "% change (100 x ln IP)"),
            ("unemp", "Unemployment Rate", "Percentage points (pp)"),
            ("ebp", "Excess Bond Premium", "Percentage points (pp)"),
            ("log_cpi", "CPI Price Level", "% change (100 x ln CPI)"),
        ]

        fig1, axes1 = plt.subplots(2, 2, figsize=(9.8, 7.2), sharex=True)
        for ax, (outcome, title, ylabel) in zip(axes1.flat, panels, strict=True):
            orth = lp_irfs[(lp_irfs["spec_name"] == "lp_orth") & (lp_irfs["outcome"] == outcome)].sort_values("horizon")
            raw = lp_irfs[(lp_irfs["spec_name"] == "lp_raw") & (lp_irfs["outcome"] == outcome)].sort_values("horizon")
            rob = lp_irfs[(lp_irfs["spec_name"] == "lp_orth_robust") & (lp_irfs["outcome"] == outcome)].sort_values("horizon")
            h = orth["horizon"].to_numpy()
            ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
            ax.fill_between(h, orth["coef"] - 1.645 * orth["se"], orth["coef"] + 1.645 * orth["se"], color="#1f4e79", alpha=0.18, label="90% HAC CI (orth)")
            ax.plot(h, orth["coef"], color="#1f4e79", linewidth=2.0, label="LP: MPS orth (6 lags)")
            ax.plot(raw["horizon"], raw["coef"], color="#b22222", linestyle="--", linewidth=1.7, label="LP: MPS raw (6 lags)")
            ax.plot(rob["horizon"], rob["coef"], color="#2e8b57", linestyle=":", linewidth=1.6, label="LP: MPS orth (12 lags)")
            ax.set_title(title, fontsize=10)
            ax.set_ylabel(ylabel, fontsize=8.5)
            ax.grid(True, linestyle="--", alpha=0.3)
        axes1[1, 0].set_xlabel("Horizon (months)")
        axes1[1, 1].set_xlabel("Horizon (months)")
        axes1[0, 0].legend(fontsize=7.5, frameon=True, loc="best")
        fig1.suptitle("Local Projections: Response to a +100 bp (+1.0 pp) Monetary Policy Surprise", fontsize=11.5, y=0.98)
        fig1.text(0.5, 0.935, "Shock scale: 1-unit MPS surprise (+100 bp; 1 SD ~ 5 bp; divide by 4 for +25 bp). Shaded band: 90% HAC CI.", ha="center", fontsize=8.5, color="#333333")
        fig1.tight_layout(rect=[0, 0, 1, 0.92])
        self._save(fig1, config, "lp_orth_vs_raw_irfs.png", data=data)

        fig2, axes2 = plt.subplots(2, 2, figsize=(9.8, 7.2), sharex=True)
        for ax, (outcome, title, ylabel) in zip(axes2.flat, panels, strict=True):
            p_orth = struct_irfs[(struct_irfs["spec_name"] == "psvar_orth") & (struct_irfs["outcome"] == outcome)].sort_values("horizon")
            p_raw = struct_irfs[(struct_irfs["spec_name"] == "psvar_raw") & (struct_irfs["outcome"] == outcome)].sort_values("horizon")
            lpiv = struct_irfs[(struct_irfs["spec_name"] == "lpiv_orth") & (struct_irfs["outcome"] == outcome)].sort_values("horizon")
            ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
            ax.plot(p_orth["horizon"], p_orth["coef"], color="#1f4e79", linewidth=2.0, label=f"Proxy-SVAR: MPS orth (+{impact_bp} bp)")
            ax.plot(p_raw["horizon"], p_raw["coef"], color="#b22222", linestyle="--", linewidth=1.7, label=f"Proxy-SVAR: MPS raw (+{impact_bp} bp)")
            ax.plot(lpiv["horizon"], lpiv["coef"], color="#2e8b57", linestyle="-.", linewidth=1.6, label=f"LP-IV: MPS orth (+{impact_bp} bp)")
            ax.set_title(title, fontsize=10)
            ax.set_ylabel(ylabel, fontsize=8.5)
            ax.grid(True, linestyle="--", alpha=0.3)
        axes2[1, 0].set_xlabel("Horizon (months)")
        axes2[1, 1].set_xlabel("Horizon (months)")
        axes2[0, 0].legend(fontsize=7.5, frameon=True, loc="best")
        fig2.suptitle(f"Structural IRFs: Response to a +{impact_bp} bp Impact Shock on 2Y Treasury Yield (treas_2y)", fontsize=11.5, y=0.98)
        fig2.text(0.5, 0.935, f"Shock scale: normalized to a +{impact_bp} bp (+{impact_bp / 100.0:.2f} pp) impact increase in treas_2y (Proxy-SVAR and LP-IV, 6 lags).", ha="center", fontsize=8.5, color="#333333")
        fig2.tight_layout(rect=[0, 0, 1, 0.92])
        self._save(fig2, config, "structural_irfs.png", data=data)
