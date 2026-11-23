import pytest

from reproducible_econ.pipeline.graph import StageGraph
from reproducible_econ.pipeline.stage import BaseStage, StageDefinition


class DummyStage(BaseStage):
    def __init__(self, scale=1):
        self.scale = scale

    def run(self, data, config):
        return data


class NotRunnable:
    pass


def _spec(name, requires=None, produces=None, phase="default", order=None, enabled_config=None):
    item = {
        "name": name,
        "module": __name__,
        "class": "DummyStage",
        "phase": phase,
        "requires": requires or [],
        "produces": produces or [],
    }
    if order is not None:
        item["order"] = order
    if enabled_config is not None:
        item["enabled_config"] = enabled_config
    return item


def test_stage_definition_class_resolution_and_build():
    via_default = StageDefinition.from_dict({"name": "a", "class": "DummyStage", "init_args": {"scale": 5}}, default_module=__name__)
    inst = via_default.build()
    assert isinstance(inst, DummyStage)
    assert inst.scale == 5
    assert via_default.class_path == f"{__name__}.DummyStage"

    via_path = StageDefinition.from_dict({"name": "b", "class_path": f"{__name__}.DummyStage"})
    assert isinstance(via_path.build(), DummyStage)


def test_stage_definition_invalid_specs():
    with pytest.raises(ValueError, match="cannot specify both"):
        StageDefinition.from_dict({"name": "x", "module": __name__, "class": "DummyStage", "class_path": f"{__name__}.DummyStage"})
    with pytest.raises(ValueError, match="must specify"):
        StageDefinition.from_dict({"name": "x"})
    with pytest.raises(ValueError, match="default_module"):
        StageDefinition.from_dict({"name": "x", "class": "DummyStage"})
    with pytest.raises(ValueError, match="module.ClassName"):
        StageDefinition.from_dict({"name": "x", "class_path": "NoDot"})
    bad_stage = StageDefinition.from_dict({"name": "bad", "module": __name__, "class": "NotRunnable"})
    with pytest.raises(TypeError, match="callable run"):
        bad_stage.build()


def test_graph_validation_errors():
    with pytest.raises(ValueError, match="Duplicate stage name"):
        StageGraph([StageDefinition.from_dict(_spec("s1")), StageDefinition.from_dict(_spec("s1"))])
    with pytest.raises(ValueError, match="Duplicate producer"):
        StageGraph([
            StageDefinition.from_dict(_spec("s1", produces=["a"])),
            StageDefinition.from_dict(_spec("s2", produces=["a"])),
        ])
    with pytest.raises(ValueError, match="self-dependency"):
        StageGraph([StageDefinition.from_dict(_spec("s1", requires=["a"], produces=["a"]))])
    with pytest.raises(ValueError, match="without producers"):
        StageGraph([StageDefinition.from_dict(_spec("s1", requires=["missing"]))])


def test_graph_initial_data_keys_allow_external_inputs():
    graph = StageGraph([StageDefinition.from_dict(_spec("s1", requires=["raw"], produces=["clean"]))], initial_data_keys=["raw"])
    assert [d.name for d in graph.ordered_definitions] == ["s1"]


def test_graph_cycle_detection_two_and_three_nodes():
    two = [
        StageDefinition.from_dict(_spec("a", requires=["y"], produces=["x"])),
        StageDefinition.from_dict(_spec("b", requires=["x"], produces=["y"])),
    ]
    with pytest.raises(ValueError, match="cycle detected"):
        StageGraph(two)

    three = [
        StageDefinition.from_dict(_spec("a", requires=["z"], produces=["x"])),
        StageDefinition.from_dict(_spec("b", requires=["x"], produces=["y"])),
        StageDefinition.from_dict(_spec("c", requires=["y"], produces=["z"])),
    ]
    with pytest.raises(ValueError, match="cycle detected"):
        StageGraph(three)


def test_graph_deterministic_order_and_target_closure():
    defs = [
        StageDefinition.from_dict(_spec("load", produces=["panel"], phase="data"), default_order=0),
        StageDefinition.from_dict(_spec("est", requires=["panel"], produces=["results"], phase="estimate"), default_order=1),
        StageDefinition.from_dict(_spec("tab", requires=["results"], phase="report"), default_order=2),
        StageDefinition.from_dict(_spec("fig", requires=["panel"], phase="report"), default_order=3),
    ]
    graph = StageGraph(defs)
    assert [d.name for d in graph.ordered_definitions] == ["load", "est", "tab", "fig"]
    assert [d.name for d in graph.resolve(["tab"])] == ["load", "est", "tab"]
    assert [d.name for d in graph.resolve(["fig"])] == ["load", "fig"]
    assert [d.name for d in graph.resolve(["report"])] == ["load", "est", "tab", "fig"]
    with pytest.raises(ValueError, match="Unknown target"):
        graph.resolve(["does_not_exist"])


def test_graph_order_tie_breaking():
    defs = [
        StageDefinition.from_dict(_spec("second", order=10)),
        StageDefinition.from_dict(_spec("first", order=1)),
        StageDefinition.from_dict(_spec("alpha", order=5)),
        StageDefinition.from_dict(_spec("beta", order=5)),
    ]
    graph = StageGraph(defs)
    assert [d.name for d in graph.ordered_definitions] == ["first", "alpha", "beta", "second"]


def test_disabled_stage_guard():
    defs = [
        StageDefinition.from_dict(_spec("prep", produces=["panel"], enabled_config="flags.prep"), default_order=0),
        StageDefinition.from_dict(_spec("est", requires=["panel"], produces=["est"], enabled_config="flags.est"), default_order=1),
        StageDefinition.from_dict(_spec("plot", requires=["est"], enabled_config="flags.plot"), default_order=2),
    ]
    graph = StageGraph(defs)
    graph.validate_enabled(graph.ordered_definitions, {"flags": {"prep": True, "est": True, "plot": False}})
    with pytest.raises(ValueError, match="disabled stage 'prep'"):
        graph.validate_enabled(graph.ordered_definitions, {"flags": {"prep": False, "est": True, "plot": False}})
