import re
from datetime import UTC, datetime
from pathlib import Path

import yaml

_MISSING = object()
_TOKEN_RE = re.compile(r"\$\{([A-Za-z0-9_.-]+)\}")
_FULL_TOKEN_RE = re.compile(r"^\$\{([A-Za-z0-9_.-]+)\}$")


def get_nested(mapping, dotted_key, default=_MISSING):
    """Retrieve a value from nested dicts using a dotted key path."""
    current = mapping
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            if default is not _MISSING:
                return default
            raise KeyError(dotted_key)
        current = current[part]
    return current


def resolve_project_root(config_path):
    """Find the nearest ancestor of config_path containing pyproject.toml, else its directory."""
    path = Path(config_path).resolve()
    start = path if path.is_dir() else path.parent
    for ancestor in (start, *start.parents):
        if (ancestor / "pyproject.toml").is_file():
            return ancestor
    return start


class ConfigLoader:
    """Load YAML configs with recursive includes and variable interpolation."""

    def __init__(self, run_timestamp=None):
        self._fixed_timestamp = run_timestamp
        self.last_includes = []
        self.last_run_timestamp = None
        self.last_project_root = None

    def load(self, config_path):
        """Load, merge includes, resolve ${var} tokens, and anchor relative output paths."""
        path = Path(config_path).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
        project_root = resolve_project_root(path)
        timestamp = self._fixed_timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        included_files = []
        merged = self._load_raw(path, [path], included_files, path.parent)
        builtins = {"config_dir": str(path.parent), "project_root": str(project_root), "run_timestamp": timestamp}
        resolved = self._interpolate_value(merged, merged, builtins, frozenset(), "")
        self._resolve_relative_paths(resolved, project_root)
        self.last_includes = included_files
        self.last_run_timestamp = timestamp
        self.last_project_root = project_root
        return resolved

    @staticmethod
    def _resolve_relative_paths(config, project_root):
        output = config.get("output")
        if isinstance(output, dict):
            for key, value in list(output.items()):
                if isinstance(value, str) and value and (key.endswith(("_dir", "_path"))):
                    path_val = Path(value)
                    if not path_val.is_absolute():
                        output[key] = str((project_root / path_val).resolve())
        macros = config.get("latex_macros")
        if isinstance(macros, dict) and isinstance(macros.get("output_path"), str) and macros["output_path"]:
            path_val = Path(macros["output_path"])
            if not path_val.is_absolute():
                macros["output_path"] = str((project_root / path_val).resolve())

    def _load_raw(self, path, seen_stack, included_files, root_dir):
        with path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
        if raw is None:
            raw = {}
        if not isinstance(raw, dict):
            raise TypeError(f"Config file must define a YAML mapping: {path}")
        raw = dict(raw)
        includes = raw.pop("includes", None)
        if includes is None:
            includes = []
        if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
            raise ValueError(f"'includes' must be a list of file paths in {path}")
        merged = {}
        for include_entry in includes:
            include_path = (path.parent / include_entry).resolve()
            if include_path in seen_stack:
                chain = " -> ".join(p.name for p in [*seen_stack, include_path])
                raise ValueError(f"Circular config include detected: {chain}")
            if not include_path.is_file():
                raise FileNotFoundError(f"Included config file not found: {include_path}")
            try:
                rel_label = include_path.relative_to(root_dir).as_posix()
            except ValueError:
                rel_label = include_entry
            included_files.append(rel_label)
            include_data = self._load_raw(include_path, [*seen_stack, include_path], included_files, root_dir)
            duplicates = sorted(set(merged) & set(include_data))
            if duplicates:
                raise ValueError(f"Duplicate top-level config keys from include {include_entry!r}: {duplicates}")
            merged.update(include_data)
        duplicates = sorted(set(merged) & set(raw))
        if duplicates:
            raise ValueError(f"Duplicate top-level config keys between includes and {path.name!r}: {duplicates}")
        merged.update(raw)
        return merged

    def _interpolate_value(self, value, root, builtins, resolving, current_path):
        next_resolving = resolving | {current_path} if current_path else resolving
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                child_path = f"{current_path}.{key}" if current_path else str(key)
                result[key] = self._interpolate_value(item, root, builtins, next_resolving, child_path)
            return result
        if isinstance(value, list):
            return [self._interpolate_value(item, root, builtins, next_resolving, "") for item in value]
        if isinstance(value, tuple):
            return tuple(self._interpolate_value(item, root, builtins, next_resolving, "") for item in value)
        if isinstance(value, str):
            return self._interpolate_string(value, root, builtins, next_resolving)
        return value

    def _interpolate_string(self, text, root, builtins, resolving):
        full_match = _FULL_TOKEN_RE.match(text)
        if full_match:
            return self._resolve_token(full_match.group(1), root, builtins, resolving)

        def _replace(match):
            resolved = self._resolve_token(match.group(1), root, builtins, resolving)
            return str(resolved)

        return _TOKEN_RE.sub(_replace, text)

    def _resolve_token(self, token, root, builtins, resolving):
        if token in resolving:
            raise ValueError(f"Circular variable interpolation detected: {token}")
        if token in builtins:
            return builtins[token]
        try:
            raw_val = get_nested(root, token)
        except KeyError:
            raise ValueError(f"Unresolved config variable: ${{{token}}}") from None
        return self._interpolate_value(raw_val, root, builtins, resolving | {token}, token)
