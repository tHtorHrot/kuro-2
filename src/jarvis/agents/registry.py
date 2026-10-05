"""Specialist-agent registry. KURO remains the authority and user-facing supervisor."""

from dataclasses import dataclass

from jarvis.tools.registry import ToolRegistry


@dataclass(frozen=True)
class AgentSpec:
    name: str
    description: str
    tools: frozenset[str]
    max_steps: int = 8

    def __post_init__(self):
        if not self.name or len(self.name) > 80 or not self.name.replace("_", "").isalnum():
            raise ValueError("invalid agent name")
        if not self.description or len(self.description) > 240:
            raise ValueError("invalid agent description")
        if not 1 <= self.max_steps <= 20:
            raise ValueError("agent max_steps must be 1..20")


class AgentRegistry:
    def __init__(self, tools: ToolRegistry):
        self.tools = tools
        self._agents: dict[str, AgentSpec] = {}

    def register(self, spec: AgentSpec) -> None:
        if spec.name in self._agents:
            raise ValueError(f"duplicate agent: {spec.name}")
        for tool_name in spec.tools:
            tool = self.tools.get(tool_name)
            if tool.agent != spec.name:
                raise ValueError("agent cannot claim a tool owned by another agent")
        self._agents[spec.name] = spec

    def get(self, name: str) -> AgentSpec:
        try:
            return self._agents[name]
        except KeyError:
            raise KeyError("unknown agent") from None

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._agents))
