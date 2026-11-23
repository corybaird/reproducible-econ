import argparse
import logging
import sys
from pathlib import Path

from reproducible_econ.config import ConfigLoader
from reproducible_econ.pipeline.executor import StageExecutor
from reproducible_econ.pipeline.graph import StageGraph
from reproducible_econ.pipeline.stage import StageDefinition

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Load a YAML pipeline config, resolve the stage DAG, and execute stages."""

    def __init__(self, config_path=None, no_cache=None, targets=None, initial_data=None, argv=None):
        if config_path is None:
            args = self._parse_args(argv)
            self.config_path = Path(args.config)
            self.no_cache = args.no_cache if no_cache is None else bool(no_cache)
            self.targets = args.targets if targets is None else (list(targets) if targets else None)
            if not logging.getLogger().handlers:
                logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        else:
            self.config_path = Path(config_path)
            self.no_cache = bool(no_cache) if no_cache is not None else False
            self.targets = list(targets) if targets else None
        self.initial_data = dict(initial_data) if initial_data is not None else {}
        self.manifest_path = None
        self.last_manifest = None

    @staticmethod
    def _parse_args(argv=None):
        parser = argparse.ArgumentParser(description="Run a config-driven reproducible-econ pipeline.")
        parser.add_argument("-c", "--config", required=True, help="Path to pipeline YAML config.")
        parser.add_argument("--no-cache", action="store_true", help="Ignore cached outputs and re-execute all stages.")
        parser.add_argument("-t", "--targets", nargs="+", default=None, help="Stage names or phases to execute (with upstream closure).")
        return parser.parse_args(argv)

    def run(self):
        """Execute the configured pipeline and persist the run manifest."""
        loader = ConfigLoader()
        config = loader.load(self.config_path)
        if loader.last_project_root is not None:
            project_root_str = str(loader.last_project_root)
            if project_root_str not in sys.path:
                sys.path.insert(0, project_root_str)
        stages_raw = config.get("stages")
        if not isinstance(stages_raw, list) or not stages_raw:
            raise ValueError("Config must declare a non-empty 'stages' list")
        default_module = config.get("default_module")
        definitions = [
            StageDefinition.from_dict(spec, default_order=idx, default_module=default_module)
            for idx, spec in enumerate(stages_raw)
        ]
        graph = StageGraph(definitions, initial_data_keys=self.initial_data.keys())
        selected = graph.resolve(self.targets)
        graph.validate_enabled(selected, config)

        executor = StageExecutor(
            config,
            self.config_path,
            no_cache=self.no_cache,
            config_includes=loader.last_includes,
            targets=self.targets,
            run_timestamp=loader.last_run_timestamp,
        )
        data = dict(self.initial_data)
        for defn in selected:
            if not defn.is_enabled(config):
                executor.record_skipped(
                    defn.name,
                    phase=defn.phase,
                    class_path=defn.class_path,
                    requires=defn.requires,
                    produces=defn.produces,
                )
                continue
            stage_instance = defn.build()
            data = executor.run(
                defn.name,
                stage_instance,
                data,
                cache_inputs=list(defn.cache_inputs) if defn.cache_inputs is not None else None,
                cache=defn.cache,
                output_keys=list(defn.cache_outputs),
                upstream_keys=list(defn.requires),
                phase=defn.phase,
                produces=list(defn.produces),
            )
        self.manifest_path = executor.finalize()
        self.last_manifest = executor.manifest
        logger.info("Pipeline complete; manifest written to %s", self.manifest_path)
        return data


if __name__ == "__main__":
    PipelineRunner().run()
