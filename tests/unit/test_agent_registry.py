import pytest

from jarvis.agents import AgentRegistry, AgentSpec
from jarvis.tools import ToolEffect, ToolRegistry, ToolSpec


def test_agent_can_only_claim_its_registered_tools():
    tool = ToolSpec(
        "calendar_read",
        "Read calendar",
        "calendar",
        frozenset({"calendar:read"}),
        ToolEffect.READ,
    )
    tools = ToolRegistry([tool])
    agents = AgentRegistry(tools)
    agents.register(AgentSpec("calendar", "Calendar specialist", frozenset({"calendar_read"})))
    assert agents.get("calendar").max_steps == 8
    with pytest.raises(ValueError, match="another agent"):
        AgentRegistry(tools).register(
            AgentSpec("research", "Research specialist", frozenset({"calendar_read"}))
        )
