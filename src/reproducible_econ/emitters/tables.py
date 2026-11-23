import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from reproducible_econ.emitters import record_emitted_file
from reproducible_econ.pipeline.stage import BaseStage

logger = logging.getLogger(__name__)

_LATEX_ESCAPES = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_ESCAPE_RE = re.compile("|".join(re.escape(ch) for ch in _LATEX_ESCAPES))


def escape_latex(text):
    """Escape LaTeX special characters in a single pass."""
    return _LATEX_ESCAPE_RE.sub(lambda match: _LATEX_ESCAPES[match.group(0)], str(text))


def _format_cell(value, float_format, na_rep=""):
    if pd.isna(value):
        return na_rep
    if isinstance(value, (bool, np.bool_)):
        return "True" if value else "False"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        if "%" in float_format:
            return float_format % float(value)
        return float_format.format(float(value))
    return escape_latex(value)


def dataframe_to_booktabs(frame, caption=None, label=None, note=None, float_format="%.3f", columns=None, rename=None, alignment=None, na_rep=""):
    """Render a pandas DataFrame as a standalone booktabs LaTeX table string."""
    df = frame.loc[:, list(columns)].copy() if columns is not None else frame.copy()
    rename_map = dict(rename or {})
    col_align = alignment or "".join("r" if pd.api.types.is_numeric_dtype(df[col]) else "l" for col in df.columns)
    headers = [escape_latex(rename_map.get(col, col)) for col in df.columns]

    lines = [
        "% Generated file. Do not hand edit.",
        r"\begin{table}[htbp]",
        r"\centering",
    ]
    if caption:
        lines.append(f"\\caption{{{escape_latex(caption)}}}")
    if label:
        lines.append(f"\\label{{{label}}}")
    lines.append(f"\\begin{{tabular}}{{{col_align}}}")
    lines.append(r"\toprule")
    lines.append(" & ".join(headers) + r" \\")
    lines.append(r"\midrule")
    for row in df.itertuples(index=False, name=None):
        formatted = [_format_cell(val, float_format, na_rep=na_rep) for val in row]
        lines.append(" & ".join(formatted) + r" \\")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    if note:
        lines.append(f"\\begin{{minipage}}{{\\linewidth}}\\footnotesize {escape_latex(note)}\\end{{minipage}}")
    lines.append(r"\end{table}")
    return "\n".join(lines) + "\n"


class LatexTableStage(BaseStage):
    """Export configured DataFrames to booktabs LaTeX tables (and optional CSVs)."""

    def run(self, data, config):
        """Render all declared tables under output.tables_dir and register emitted files."""
        tables_cfg = config.get("tables") or {}
        exports = tables_cfg.get("exports") or []
        strict = bool(tables_cfg.get("strict", True))
        output_cfg = config.get("output") or {}
        tables_dir = Path(output_cfg.get("tables_dir") or (Path(output_cfg.get("reports_dir", "reports")) / "tables"))
        tables_dir.mkdir(parents=True, exist_ok=True)

        for spec in exports:
            key = spec["key"]
            if key not in data:
                if strict:
                    raise KeyError(f"Table export artifact {key!r} not found in pipeline data")
                logger.warning("Skipping table export for missing artifact %r", key)
                continue
            frame = data[key]
            if not isinstance(frame, pd.DataFrame):
                raise TypeError(f"Table export artifact {key!r} must be a pandas DataFrame")
            tex_content = dataframe_to_booktabs(
                frame,
                caption=spec.get("caption"),
                label=spec.get("label"),
                note=spec.get("note"),
                float_format=spec.get("float_format", "%.3f"),
                columns=spec.get("columns"),
                rename=spec.get("rename"),
                alignment=spec.get("alignment"),
                na_rep=spec.get("na_rep", ""),
            )
            out_path = tables_dir / spec["filename"]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(tex_content, encoding="utf-8")
            record_emitted_file(data, out_path)
            logger.info("Wrote LaTeX table: %s", out_path)

            if spec.get("also_csv"):
                csv_frame = frame.loc[:, list(spec["columns"])] if spec.get("columns") is not None else frame
                csv_path = out_path.with_suffix(".csv")
                csv_frame.to_csv(csv_path, index=False)
                record_emitted_file(data, csv_path)
                logger.info("Wrote CSV table copy: %s", csv_path)
        return data
