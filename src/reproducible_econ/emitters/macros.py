import logging
import re
from pathlib import Path

import pandas as pd

from reproducible_econ.emitters import record_emitted_file
from reproducible_econ.pipeline.stage import BaseStage

logger = logging.getLogger(__name__)

DIGIT_WORDS = {
    "0": "Zero",
    "1": "One",
    "2": "Two",
    "3": "Three",
    "4": "Four",
    "5": "Five",
    "6": "Six",
    "7": "Seven",
    "8": "Eight",
    "9": "Nine",
}
FIELD_SUFFIXES = {
    "coef": "Coef",
    "se": "SE",
    "pval": "P",
    "n_obs": "N",
}
SHORT_SUFFIXES = {
    "coef": "CoefShort",
    "se": "SEShort",
}
_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def sanitize_macro_stem(name):
    """Convert a user label into a valid ASCII-letter LaTeX macro stem."""
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Macro entry 'name' must be a non-empty string")
    parts = [part for part in _SPLIT_RE.split(name) if part]
    tokens = []
    for part in parts:
        expanded = "".join(DIGIT_WORDS.get(ch, ch) for ch in part)
        if expanded:
            tokens.append(expanded[0].upper() + expanded[1:])
    stem = "".join(tokens)
    if not stem or not stem.isalpha():
        raise ValueError(f"Could not produce a valid LaTeX macro stem from {name!r}")
    return stem


def _format_macro_value(field, value, precision, short_precision, pval_precision):
    if pd.isna(value):
        raise ValueError(f"Macro field {field!r} is NaN")
    numeric = float(value)
    if field == "n_obs":
        return f"{round(numeric):,}", None
    if field == "pval":
        floor = 10 ** (-pval_precision)
        if numeric < floor:
            return f"<{floor:.{pval_precision}f}", None
        return f"{numeric:.{pval_precision}f}", None
    long_val = f"{numeric:.{precision}f}"
    short_val = f"{numeric:.{short_precision}f}" if field in SHORT_SUFFIXES else None
    return long_val, short_val


class LatexMacroStage(BaseStage):
    """Emit LaTeX \\newcommand macros from tidy estimation DataFrames with strict checks."""

    def run(self, data, config):
        """Generate a LaTeX macros file from config['latex_macros'] entries."""
        macro_cfg = config.get("latex_macros") or {}
        entries = macro_cfg.get("entries") or []
        output_cfg = config.get("output") or {}
        default_path = output_cfg.get("macros_path") or (Path(output_cfg.get("reports_dir", "reports")) / "macros.tex")
        out_path = Path(macro_cfg.get("output_path") or default_path)
        precision = int(macro_cfg.get("precision", 4))
        short_precision = int(macro_cfg.get("short_precision", 3))
        pval_precision = int(macro_cfg.get("pval_precision", 3))
        default_fields = list(macro_cfg.get("fields", ["coef", "se", "pval", "n_obs"]))
        spec_col = macro_cfg.get("spec_col", "spec_name")
        var_col = macro_cfg.get("var_col", "key_variable")

        lines = ["% Generated file. Do not hand edit."]
        seen_stems = {}
        seen_macros = set()

        for entry in entries:
            tidy_key = entry["tidy_key"]
            if tidy_key not in data or not isinstance(data[tidy_key], pd.DataFrame) or data[tidy_key].empty:
                raise ValueError(f"Macro tidy artifact {tidy_key!r} is missing or empty")
            frame = data[tidy_key]
            for required_col in (spec_col, var_col):
                if required_col not in frame.columns:
                    raise ValueError(f"Macro tidy artifact {tidy_key!r} missing required column {required_col!r}")

            spec_val = entry["spec"]
            var_val = entry["key_variable"]
            matched = frame[(frame[spec_col] == spec_val) & (frame[var_col] == var_val)]
            if len(matched) == 0:
                raise ValueError(f"No row in {tidy_key!r} matching {spec_col}={spec_val!r}, {var_col}={var_val!r}")
            if len(matched) > 1:
                raise ValueError(f"Ambiguous {len(matched)} rows in {tidy_key!r} matching {spec_col}={spec_val!r}, {var_col}={var_val!r}")
            row = matched.iloc[0]

            raw_name = entry["name"]
            stem = sanitize_macro_stem(raw_name)
            if stem in seen_stems:
                raise ValueError(f"Macro stem collision for {stem!r}: {seen_stems[stem]!r} and {raw_name!r}")
            seen_stems[stem] = raw_name

            fields = list(entry.get("fields", default_fields))
            eprec = int(entry.get("precision", precision))
            esprec = int(entry.get("short_precision", short_precision))
            epval = int(entry.get("pval_precision", pval_precision))

            for field in fields:
                if field not in frame.columns:
                    raise ValueError(f"Macro field {field!r} not found in {tidy_key!r}")
                long_val, short_val = _format_macro_value(field, row[field], eprec, esprec, epval)
                suffix = FIELD_SUFFIXES.get(field, sanitize_macro_stem(field))
                macro_name = f"{stem}{suffix}"
                if macro_name in seen_macros:
                    raise ValueError(f"Duplicate macro name: \\{macro_name}")
                seen_macros.add(macro_name)
                lines.append(f"\\newcommand{{\\{macro_name}}}{{{long_val}}}")

                if short_val is not None:
                    short_macro = f"{stem}{SHORT_SUFFIXES[field]}"
                    if short_macro in seen_macros:
                        raise ValueError(f"Duplicate macro name: \\{short_macro}")
                    seen_macros.add(short_macro)
                    lines.append(f"\\newcommand{{\\{short_macro}}}{{{short_val}}}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        record_emitted_file(data, out_path)
        logger.info("Wrote LaTeX macros: %s (%d macros)", out_path, len(seen_macros))
        return data
