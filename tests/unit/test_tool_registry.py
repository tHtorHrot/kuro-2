import pytest

from jarvis.tools import ToolEffect, ToolRegistry, ToolSpec


def calendar_read(**kwargs):
    return ToolSpec(
        "calendar_read",
        "Read calendar",
        "calendar",
        frozenset({"calendar:read"}),
        ToolEffect.READ,
        **kwargs,
    )


def test_registry_is_closed_and_agent_scoped():
    read = calendar_read()
    registry = ToolRegistry([read])
    assert registry.get("calendar_read") is read
    assert registry.for_agent("calendar") == (read,)
    with pytest.raises(KeyError, match="unknown tool"):
        registry.get("model_invented_tool")
    with pytest.raises(ValueError, match="duplicate tool"):
        registry.register(read)


def test_network_allowlist_accepts_hostnames_not_arbitrary_urls():
    calendar_read(network_targets=("www.googleapis.com",))
    with pytest.raises(ValueError, match="hostnames"):
        calendar_read(network_targets=("https://evil.example/path",))
