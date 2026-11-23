import heapq


class StageGraph:
    """Directed acyclic graph of pipeline stages with topological ordering."""

    def __init__(self, definitions, initial_data_keys=None):
        self._definitions = list(definitions)
        self._initial_keys = set(initial_data_keys or ())
        self.by_name = {}
        self.producers = {}
        for defn in self._definitions:
            if defn.name in self.by_name:
                raise ValueError(f"Duplicate stage name: {defn.name!r}")
            self.by_name[defn.name] = defn
            overlap = sorted(set(defn.requires) & set(defn.produces))
            if overlap:
                raise ValueError(f"Stage {defn.name!r} has self-dependency on artifacts: {overlap}")
            for artifact in defn.produces:
                if artifact in self.producers:
                    raise ValueError(f"Duplicate producer for artifact {artifact!r}: {self.producers[artifact]!r} and {defn.name!r}")
                self.producers[artifact] = defn.name
        self.dependencies = {defn.name: set() for defn in self._definitions}
        self._dependents = {defn.name: set() for defn in self._definitions}
        for defn in self._definitions:
            missing = [a for a in defn.requires if a not in self.producers and a not in self._initial_keys]
            if missing:
                raise ValueError(f"Stage {defn.name!r} requires artifacts without producers: {missing}")
            for artifact in defn.requires:
                producer = self.producers.get(artifact)
                if producer is not None:
                    self.dependencies[defn.name].add(producer)
                    self._dependents[producer].add(defn.name)
        self.ordered_definitions = self._topological_sort()

    def _topological_sort(self):
        in_degree = {name: len(deps) for name, deps in self.dependencies.items()}
        ready = []
        for defn in self._definitions:
            if in_degree[defn.name] == 0:
                heapq.heappush(ready, (defn.order, defn.name))
        ordered = []
        while ready:
            _, name = heapq.heappop(ready)
            ordered.append(self.by_name[name])
            for dependent in self._dependents[name]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    dep_defn = self.by_name[dependent]
                    heapq.heappush(ready, (dep_defn.order, dep_defn.name))
        if len(ordered) != len(self._definitions):
            placed = {d.name for d in ordered}
            remaining = sorted(name for name in self.by_name if name not in placed)
            raise ValueError(f"Stage dependency cycle detected: {remaining}")
        return ordered

    def resolve(self, targets=None):
        """Return target stages plus their transitive upstream closure in topo order."""
        if not targets:
            return list(self.ordered_definitions)
        phase_map = {}
        for defn in self._definitions:
            phase_map.setdefault(defn.phase, []).append(defn.name)
        expanded = []
        for target in targets:
            if target in self.by_name:
                expanded.append(target)
            elif target in phase_map:
                expanded.extend(phase_map[target])
            else:
                raise ValueError(f"Unknown target stage or phase: {target!r}")
        needed = self._closure(expanded)
        return [defn for defn in self.ordered_definitions if defn.name in needed]

    def _closure(self, names):
        needed = set()
        stack = list(names)
        while stack:
            current = stack.pop()
            if current in needed:
                continue
            needed.add(current)
            for dep in self.dependencies[current]:
                if dep not in needed:
                    stack.append(dep)
        return needed

    def validate_enabled(self, definitions, config):
        """Ensure no enabled stage depends on an artifact from a disabled stage."""
        enabled = {defn.name for defn in definitions if defn.is_enabled(config)}
        included = {defn.name for defn in definitions}
        for defn in definitions:
            if defn.name not in enabled:
                continue
            for artifact in defn.requires:
                producer = self.producers.get(artifact)
                if producer is not None and producer in included and producer not in enabled:
                    raise ValueError(f"Enabled stage {defn.name!r} requires artifact {artifact!r} from disabled stage {producer!r}")
