import importlib

from reproducible_econ import emitters
from reproducible_econ.config import ConfigLoader
from reproducible_econ.pipeline.executor import StageExecutor
from reproducible_econ.pipeline.graph import StageGraph
from reproducible_econ.pipeline.stage import BaseStage, StageDefinition

__all__ = [
    "BaseStage",
    "ConfigLoader",
    "PipelineRunner",
    "StageDefinition",
    "StageExecutor",
    "StageGraph",
    "emitters",
]
__version__ = "0.1.0"


def __getattr__(name):
    if name == "PipelineRunner":
        return importlib.import_module("reproducible_econ.pipeline.runner").PipelineRunner
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
