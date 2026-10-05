"""Closed tool registry. Tools are application code, never dynamically supplied by an LLM."""

from collections.abc import Iterable

from jarvis.tools.contracts import ToolSpec


class ToolRegistry:
    def __init__(self, specs: Iterable[ToolSpec] = ()):
        self._specs: dict[str, ToolSpec] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._specs:
            raise ValueError(f"duplicate tool: {spec.name}")
        self._specs[spec.name] = spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise KeyError("unknown tool") from None

    def for_agent(self, agent: str) -> tuple[ToolSpec, ...]:
        return tuple(spec for spec in self._specs.values() if spec.agent == agent)

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))
