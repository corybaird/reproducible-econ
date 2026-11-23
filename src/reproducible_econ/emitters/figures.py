import contextlib
import importlib
import logging
import sys
from abc import abstractmethod
from pathlib import Path

from reproducible_econ.emitters import record_emitted_file
from reproducible_econ.pipeline.stage import BaseStage

logger = logging.getLogger(__name__)

_INSTALL_HINT = "Install with: uv add 'reproducible-econ[figures]'"


class FigureStageBase(BaseStage):
    """Base stage for matplotlib figures with lazy import and graceful skip."""

    def run(self, data, config):
        """Load matplotlib lazily, apply optional style, and invoke _plot()."""
        plt = self._pyplot(config)
        if plt is None:
            return data
        with self._style_context(plt, config):
            self._plot(data, config, plt)
        return data

    @abstractmethod
    def _plot(self, data, config, plt):
        """Render figure(s) using plt and save via self._save()."""

    def _pyplot(self, config):
        plotting = config.get("plotting") or {}
        on_missing = plotting.get("on_missing_matplotlib", "skip")
        try:
            matplotlib = importlib.import_module("matplotlib")
            if "matplotlib.pyplot" not in sys.modules:
                matplotlib.use("Agg")
            return importlib.import_module("matplotlib.pyplot")
        except ImportError as exc:
            if on_missing == "error":
                raise ImportError(f"matplotlib is required for {self.__class__.__name__}. {_INSTALL_HINT}") from exc
            logger.warning("matplotlib not installed; skipping figure stage %s. %s", self.__class__.__name__, _INSTALL_HINT)
            return None

    @staticmethod
    def _style_context(plt, config):
        style = (config.get("plotting") or {}).get("style")
        if style:
            return plt.style.context(style)
        return contextlib.nullcontext()

    def _save(self, fig, config, filename, data=None, subdirectory=None, dpi=None):
        output_cfg = config.get("output") or {}
        plotting_cfg = config.get("plotting") or {}
        base_dir = Path(output_cfg.get("figures_dir") or (Path(output_cfg.get("reports_dir", "reports")) / "figures"))
        out_dir = base_dir / subdirectory if subdirectory else base_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / filename
        resolved_dpi = int(dpi if dpi is not None else plotting_cfg.get("dpi", 200))
        fig.savefig(out_path, bbox_inches="tight", dpi=resolved_dpi)
        plt = importlib.import_module("matplotlib.pyplot")
        plt.close(fig)
        logger.info("Wrote figure: %s", out_path)
        record_emitted_file(data, out_path)
        return out_path
