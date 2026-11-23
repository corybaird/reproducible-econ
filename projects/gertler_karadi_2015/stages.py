import logging
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from stats_transformer.models import ProxySVARModel

from reproducible_econ.emitters.figures import FigureStageBase
from reproducible_econ.pipeline.stage import BaseStage

logger = logging.getLogger(__name__)

GK_COLUMNS = ["date", "logcpi", "logip", "gs1", "ebp", "ff4_tc"]


class PrepareGKPanelStage(BaseStage):
    """Load the Gertler-Karadi (2015) AEJ replication workbook and select variables by mnemonic."""

    def run(self, data, config):
        """Read GK2015_Data.xlsx, map sentinels to NaN, and keep date + VAR variables + instrument."""
        data_cfg = config.get("data") or {}
        data_path = Path(data_cfg["data_path"])
        sentinel = float(data_cfg.get("sentinel", 123456789.0))

        raw = pd.read_excel(data_path, sheet_name="Sheet1", header=None)
        mnem = raw.iloc[1]
        rename = {i: str(name) for i, name in mnem.items() if pd.notna(name)}
        frame = raw.iloc[2:].rename(columns=rename).reset_index(drop=True)
        frame = frame.rename(columns={frame.columns[0]: "date"})

        missing = [col for col in GK_COLUMNS if col not in frame.columns]
        if missing:
            raise ValueError(f"Workbook mnemonics missing: {missing}")
        frame = frame[GK_COLUMNS].copy()
        for col in GK_COLUMNS[1:]:
            frame[col] = pd.to_numeric(frame[col], errors="coerce").replace(sentinel, np.nan)

        svar_cfg = config.get("svar") or {}
        endog = list(svar_cfg["target_variables"])
        instrument = str(svar_cfg["instrument_variable"])
        missing = [col for col in [instrument] if col not in frame.columns]
        if missing:
            raise ValueError(f"Instrument column not found in workbook: {missing}")
        panel = frame[["date", *endog, instrument]].reset_index(drop=True)
        if panel[endog].isna().any().any():
            raise ValueError("NaN in endogenous variables; VAR sample would change")

        logger.info(
            "Prepared GK panel: %d months (%s to %s), %d non-missing instrument observations",
            len(panel),
            panel["date"].iloc[0],
            panel["date"].iloc[-1],
            panel[instrument].notna().sum(),
        )
        data["gk_panel"] = panel
        return data


class EstimateProxySvarStage(BaseStage):
    """Estimate the Gertler-Karadi (2015) proxy-SVAR and the first-stage instrument regression."""

    def run(self, data, config):
        """Fit ProxySVARModel (12 lags, ff4_tc instrument), collect IRFs and first-stage F stats."""
        panel = data["gk_panel"].copy()
        svar_cfg = config.get("svar") or {}
        endog = list(svar_cfg["target_variables"])
        instrument = str(svar_cfg["instrument_variable"])
        maxlags = int(svar_cfg.get("maxlags", 12))
        irf_horizons = int(svar_cfg.get("irf_horizons", 48))
        claim_horizons = [int(h) for h in svar_cfg.get("claim_horizons", [0, 12, 24])]
        table_horizons = [int(h) for h in svar_cfg.get("table_horizons", [0, 3, 6, 12, 24, 48])]

        fit_frame = panel[endog + [instrument]]
        model = ProxySVARModel(target_variables=endog, instrument_variable=instrument, maxlags=maxlags)
        metrics = model.fit(fit_frame)
        n_obs = int(metrics["nobs"])
        impact = np.asarray(model.impact_column, dtype=float)
        logger.info(
            "Proxy-SVAR: %d VAR observations, %d lags, first-stage sample %d",
            n_obs,
            maxlags,
            panel[instrument].notna().sum(),
        )

        irf = model.irf(horizons=irf_horizons)
        irf_rows = []
        headline_rows = []
        for h in range(irf_horizons):
            for var in endog:
                coef = float(irf.iloc[h][var])
                if h in table_horizons:
                    headline_rows.append({"spec_name": "psvar", "key_variable": var, "horizon": h, "coef": coef, "n_obs": n_obs})
                if h in claim_horizons:
                    irf_rows.append({"spec_name": f"psvar_h{h}", "key_variable": var, "horizon": h, "coef": coef, "n_obs": n_obs})
        data["svar_irfs"] = pd.DataFrame(irf_rows)
        data["irf_headline"] = pd.DataFrame(headline_rows)

        # First stage: OLS of the instrumented (gs1) VAR residual on the instrument plus constant.
        resid = model.var_result.resid.iloc[:, 0].astype(float)
        z = fit_frame.loc[resid.index, instrument]
        common = z.notna()
        fit = sm.OLS(resid[common], sm.add_constant(z[common].astype(float))).fit()
        data["first_stage"] = pd.DataFrame(
            [
                {
                    "spec_name": "first_stage",
                    "key_variable": instrument,
                    "coef": float(fit.tvalues.iloc[1]) ** 2,
                    "tstat": float(fit.tvalues.iloc[1]),
                    "r2": float(fit.rsquared),
                    "beta_const": float(fit.params.iloc[0]),
                    "beta_iv": float(fit.params.iloc[1]),
                    "n_obs": int(fit.nobs),
                }
            ]
        )
        data["svar_impact"] = pd.DataFrame(
            [{"spec_name": "impact", "key_variable": var, "coef": float(impact[i]), "n_obs": n_obs} for i, var in enumerate(endog)]
        )
        return data


class GKIRFFigureStage(FigureStageBase):
    """Plot proxy-SVAR IRFs to a one-standard-deviation monetary policy shock."""

    def _plot(self, data, config, plt):
        irfs = data["svar_irfs"]
        first_stage = data["first_stage"]
        fstat = float(first_stage["coef"].iloc[0])
        nrows = int(first_stage["n_obs"].iloc[0])
        panels = [
            ("gs1", "Policy Rate (gs1)", "Percentage points (pp)"),
            ("logcpi", "CPI Price Level (logcpi)", "Log points (x100)"),
            ("logip", "Industrial Production (logip)", "Log points (x100)"),
            ("ebp", "Excess Bond Premium (ebp)", "Percentage points (pp)"),
        ]

        fig, axes = plt.subplots(2, 2, figsize=(9.8, 7.2), sharex=True)
        for ax, (outcome, title, ylabel) in zip(axes.flat, panels, strict=True):
            series = irfs[irfs["key_variable"] == outcome].sort_values("horizon")
            ax.axhline(0.0, color="black", linewidth=0.8, alpha=0.6)
            ax.plot(series["horizon"], series["coef"], color="#1f4e79", linewidth=2.0)
            ax.set_title(title, fontsize=10)
            ax.set_ylabel(ylabel, fontsize=8.5)
            ax.grid(True, linestyle="--", alpha=0.3)
        axes[1, 0].set_xlabel("Horizon (months)")
        axes[1, 1].set_xlabel("Horizon (months)")
        fig.suptitle("Gertler and Karadi (2015) Proxy-SVAR: IRFs to a One-SD Monetary Policy Shock", fontsize=11.5, y=0.98)
        fig.text(
            0.5,
            0.935,
            f"VAR in gs1, logcpi, logip, ebp; 12 lags + constant; instrument ff4_tc (first-stage F = {fstat:.4f}, N = {nrows}).",
            ha="center",
            fontsize=8.5,
            color="#333333",
        )
        fig.tight_layout(rect=[0, 0, 1, 0.92])
        self._save(fig, config, "gk_psvar_irfs.png", data=data)
