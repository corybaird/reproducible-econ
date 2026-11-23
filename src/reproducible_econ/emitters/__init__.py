from pathlib import Path

from reproducible_econ.pipeline.executor import EMITTED_FILES_KEY


def record_emitted_file(data, path):
    """Register an emitted file path in data so StageExecutor records it in the manifest."""
    if data is None:
        return
    resolved = str(Path(path))
    emitted = data.setdefault(EMITTED_FILES_KEY, [])
    if resolved not in emitted:
        emitted.append(resolved)


from reproducible_econ.emitters.claims import ClaimCheck, ClaimCheckStage
from reproducible_econ.emitters.figures import FigureStageBase
from reproducible_econ.emitters.macros import (
    DIGIT_WORDS,
    FIELD_SUFFIXES,
    SHORT_SUFFIXES,
    LatexMacroStage,
)
from reproducible_econ.emitters.tables import LatexTableStage

__all__ = [
    "DIGIT_WORDS",
    "FIELD_SUFFIXES",
    "SHORT_SUFFIXES",
    "ClaimCheck",
    "ClaimCheckStage",
    "FigureStageBase",
    "LatexMacroStage",
    "LatexTableStage",
    "record_emitted_file",
]
