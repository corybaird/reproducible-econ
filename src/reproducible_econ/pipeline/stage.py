import importlib
from abc import ABC, abstractmethod

from reproducible_econ.config import get_nested


class BaseStage(ABC):
    """Contract for pipeline stages that transform a shared artifact dict."""

    @abstractmethod
    def run(self, data, config):
        """Execute the stage and return the updated artifact dictionary."""


class StageDefinition:
    """Normalized specification and dynamic loader for a declared pipeline stage."""

    def __init__(self, name, module, class_name, phase="default", order=0, requires=None, produces=None, cache=False, cache_inputs=None, cache_outputs=None, init_args=None, enabled_config=None):
        self.name = name
        self.module = module
        self.class_name = class_name
        self.phase = phase
        self.order = order
        self.requires = tuple(requires or ())
        self.produces = tuple(produces or ())
        self.cache = bool(cache)
        self.cache_inputs = tuple(cache_inputs) if cache_inputs is not None else None
        self.cache_outputs = tuple(cache_outputs) if cache_outputs is not None else self.produces
        self.init_args = dict(init_args) if init_args is not None else {}
        self.enabled_config = enabled_config

    @property
    def class_path(self):
        return f"{self.module}.{self.class_name}"

    @classmethod
    def from_dict(cls, spec, default_order=0, default_module=None):
        """Build a StageDefinition from a YAML stage dictionary."""
        if not isinstance(spec, dict):
            raise TypeError("Stage specification must be a mapping")
        name = spec.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Stage specification requires a non-empty string 'name'")
        module, class_name = cls._resolve_class_spec(spec, name, default_module)
        order = spec.get("order", default_order)
        if not isinstance(order, int) or isinstance(order, bool):
            raise TypeError(f"Stage {name!r} 'order' must be an integer")
        requires = spec.get("requires") or []
        produces = spec.get("produces") or []
        cache_inputs = spec.get("cache_inputs")
        cache_outputs = spec.get("cache_outputs")
        init_args = spec.get("init_args") or {}
        if not isinstance(init_args, dict):
            raise TypeError(f"Stage {name!r} 'init_args' must be a mapping")
        return cls(
            name=name,
            module=module,
            class_name=class_name,
            phase=spec.get("phase", "default"),
            order=order,
            requires=requires,
            produces=produces,
            cache=bool(spec.get("cache", False)),
            cache_inputs=cache_inputs,
            cache_outputs=cache_outputs,
            init_args=init_args,
            enabled_config=spec.get("enabled_config"),
        )

    @staticmethod
    def _resolve_class_spec(spec, name, default_module):
        class_path = spec.get("class_path")
        class_name = spec.get("class")
        module = spec.get("module")
        if class_path is not None and (class_name is not None or module is not None):
            raise ValueError(f"Stage {name!r} cannot specify both 'class_path' and 'module'/'class'")
        if class_path is not None:
            if not isinstance(class_path, str) or "." not in class_path:
                raise ValueError(f"Stage {name!r} 'class_path' must be 'module.ClassName'")
            mod_part, cls_part = class_path.rsplit(".", 1)
            if not mod_part or not cls_part:
                raise ValueError(f"Stage {name!r} 'class_path' must be 'module.ClassName'")
            return mod_part, cls_part
        if class_name is None:
            raise ValueError(f"Stage {name!r} must specify 'class' or 'class_path'")
        resolved_module = module or default_module
        if not resolved_module:
            raise ValueError(f"Stage {name!r} requires 'module' or top-level 'default_module'")
        return resolved_module, class_name

    def is_enabled(self, config):
        """Return True if the stage is enabled under the given config."""
        if self.enabled_config is None:
            return True
        return bool(get_nested(config, self.enabled_config, default=False))

    def build(self):
        """Import the stage class, instantiate it with init_args, and verify run()."""
        mod = importlib.import_module(self.module)
        cls = getattr(mod, self.class_name)
        instance = cls(**self.init_args)
        if not callable(getattr(instance, "run", None)):
            raise TypeError(f"Stage {self.name!r} instance must expose a callable run() method")
        return instance
