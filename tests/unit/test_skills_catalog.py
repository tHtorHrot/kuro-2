"""Stage 7 skills: discovery, lazy-load, capability gate (offline)."""

from jarvis.agents.roles import has_capability, require_capability
from jarvis.skills.catalog import discover_skills, read_skill, skill_sha


def test_discovery_finds_shipped_skills_with_capabilities():
    skills = discover_skills()
    assert {"research", "knowledge", "planner", "documents"} <= set(skills)
    assert skills["research"].capabilities >= {"read_only", "local_index", "citations"}
    assert skills["research"].tools == frozenset({"knowledge_search", "knowledge_read"})
    assert "Dipicu oleh task role research" in skills["research"].description


def test_discovery_skips_malformed_and_duplicate_names(tmp_path, monkeypatch):
    import jarvis.skills.catalog as catalog

    (tmp_path / "good").mkdir()
    (tmp_path / "good" / "SKILL.md").write_text(
        "---\nname: good\ndescription: ok\ntools: a\ncapabilities: read_only\n---\n# G\n"
    )
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "SKILL.md").write_text("tanpa frontmatter")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "SKILL.md").write_text(
        "---\nname: good\ndescription: duplikat\n---\n# D\n"
    )
    monkeypatch.setattr(catalog, "SKILL_FILE", "SKILL.md")
    found = discover_skills(tmp_path)
    assert list(found) == ["good"]
    assert found["good"].description == "ok"


def test_lazy_read_returns_skill_or_single_command(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n# Demo\n")
    (tmp_path / "demo" / "commands").mkdir()
    (tmp_path / "demo" / "commands" / "deep.md").write_text("# Deep\n")
    assert "# Demo" in read_skill(tmp_path, "demo")
    assert read_skill(tmp_path, "demo", "deep") == "# Deep\n"
    assert read_skill(tmp_path, "demo", "missing") is None
    assert read_skill(tmp_path, "ghost") is None
    assert read_skill(tmp_path, "demo", "../evil") is None


def test_capability_gate_blocks_write_roles_from_read_only_worker():
    require_capability(["research", "knowledge"], "read_only")
    assert has_capability("research", "citations")
    assert not has_capability("knowledge", "citations")
    try:
        require_capability(["research", "coding"], "read_only")
    except ValueError as exc:
        assert "capability_denied:read_only:coding" in str(exc)
    else:
        raise AssertionError("coding must be denied")


def test_skill_sha_stable_and_hex():
    skills = discover_skills()
    digest = skill_sha(skills["research"])
    assert len(digest) == 16 and all(c in "0123456789abcdef" for c in digest)
    assert skill_sha(skills["research"]) == digest
