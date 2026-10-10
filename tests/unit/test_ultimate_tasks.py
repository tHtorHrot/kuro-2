"""KURO Ultimate unit gates — failure matrix Bagian 7.2 (offline, tanpa DB)."""

from pathlib import Path
from uuid import uuid4

import pytest

from jarvis.agents.roles import role_exists
from jarvis.artifacts.repository import validate_rel_path
from jarvis.assistant.routing_policy import route_job
from jarvis.execution.protocol import intersect_scopes, mint_capability, verify_capability
from jarvis.execution.sandbox import SandboxError, SandboxProfile, docker_args
from jarvis.execution.workspace import WorkspaceError, resolve_inside
from jarvis.memory.repository import MemoryFact, MemoryPolicyError, validate_fact
from jarvis.orchestration.contracts import MAX_ACTIVE_WORKERS, TaskError
from jarvis.orchestration.evaluation import (
    eval_calendar,
    eval_code,
    eval_communication,
    eval_data,
    eval_research,
)
from jarvis.orchestration.model_policy import TaskPolicyError, build_task_brief
from jarvis.orchestration.planner import plan_goal, validate_plan


def test_planner_rejects_cycle():
    with pytest.raises(TaskError) as exc:
        validate_plan(
            [
                {
                    "key": "a",
                    "title": "A",
                    "role": "research",
                    "acceptance": {"criteria": ["x"]},
                    "depends_on": ["b"],
                },
                {
                    "key": "b",
                    "title": "B",
                    "role": "research",
                    "acceptance": {"criteria": ["x"]},
                    "depends_on": ["a"],
                },
            ]
        )
    assert exc.value.code == "plan_cycle_rejected"


def test_planner_rejects_unknown_tool_role():
    with pytest.raises(TaskError) as exc:
        validate_plan(
            [{"key": "a", "title": "A", "role": "nope", "acceptance": {"criteria": ["x"]}}]
        )
    assert exc.value.code == "plan_unknown_role"


def test_planner_rejects_self_dependency():
    with pytest.raises(TaskError) as exc:
        validate_plan(
            [
                {
                    "key": "a",
                    "title": "A",
                    "role": "research",
                    "acceptance": {"criteria": ["x"]},
                    "depends_on": ["a"],
                }
            ]
        )
    assert exc.value.code == "plan_self_dependency"


def test_planner_rejects_too_many_tasks():
    nodes = [
        {"key": f"t{i}", "title": f"T{i}", "role": "research", "acceptance": {"criteria": ["x"]}}
        for i in range(21)
    ]
    with pytest.raises(TaskError) as exc:
        validate_plan(nodes)
    assert exc.value.code == "plan_task_count_invalid"


def test_plan_goal_single_read_only():
    plan = plan_goal("ringkas dokumen ini")
    assert len(plan.nodes) == 1
    assert role_exists(plan.nodes[0].role)


def test_workspace_rejects_escape(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    with pytest.raises(WorkspaceError):
        resolve_inside(root, "../secret")
    with pytest.raises(WorkspaceError):
        resolve_inside(root, "/abs")
    ok = resolve_inside(root, "a/b.txt")
    assert str(ok).startswith(str(root.resolve()))


def test_sandbox_defaults_deny_network_and_mounts():
    profile = SandboxProfile(command=("python", "-c", "pass"))
    args = docker_args(profile, workspace=Path("/tmp/ws"))
    assert "--network" in args and "none" in args
    assert "--cap-drop" in args
    with pytest.raises(SandboxError):
        SandboxProfile(extra_mounts=("/etc",), command=("x",))
    with pytest.raises(SandboxError):
        docker_args(SandboxProfile(allow_network=True, command=("x",)), workspace=Path("/tmp/ws"))


def test_capability_roundtrip_and_expiry():
    owner, task, run = uuid4(), uuid4(), uuid4()
    cap = mint_capability(
        secret="s",
        owner_id=owner,
        task_id=task,
        run_id=run,
        ttl_seconds=300,
        tools=frozenset({"knowledge_search"}),
    )
    back = verify_capability("s", cap.token)
    assert back.task_id == task
    with pytest.raises(ValueError):
        verify_capability("wrong", cap.token)


def test_scope_intersection_never_grows():
    base = frozenset({"a", "b"})
    assert intersect_scopes(base, frozenset({"b", "c"})) == frozenset({"b"})
    assert intersect_scopes(base, frozenset()) == frozenset()


def test_artifact_path_validation():
    validate_rel_path("report.md")
    with pytest.raises(TaskError):
        validate_rel_path("/etc/passwd")
    with pytest.raises(TaskError):
        validate_rel_path("../x")


def test_eval_research_rejects_unknown_label():
    result = eval_research(answer="klaim [S9]", source_ids=["S1"])
    assert not result.passed
    ok = eval_research(
        answer="hasil 10. [S1]", source_ids=["S1"], supported_claims=1, total_claims=1
    )
    assert ok.passed


def test_eval_code_requires_files_and_no_forbidden():
    assert not eval_code(files={}).passed
    assert not eval_code(files={"../x": "y"}).passed
    assert eval_code(files={"main.py": "print(1)"}, required_files=["main.py"]).passed


def test_eval_data_row_count():
    assert not eval_data(rows=[{"a": 1}], expected_count=2).passed
    assert eval_data(rows=[{"a": 1}], expected_count=1).passed


def test_eval_calendar_and_communication():
    assert eval_calendar(fingerprint="ab", expected_fingerprint="ab").passed
    assert not eval_calendar(fingerprint="ab", expected_fingerprint="cd").passed
    r = eval_communication(
        recipient="a@x", expected_recipient="a@x", payload_hash="h", approved_hash=None
    )
    assert not r.passed and r.needs_human


def test_task_brief_rejects_oversize_title():
    with pytest.raises(TaskPolicyError):
        build_task_brief(title="", acceptance={}, constraints={})


def test_routing_parse_needs_no_llm():
    assert route_job("parse").model is None
    assert route_job("plan").model_class == "reasoning"


def test_memory_requires_provenance():
    with pytest.raises(MemoryPolicyError):
        validate_fact(MemoryFact(key="k", value="v", provenance=""))
    validate_fact(MemoryFact(key="k", value="v", provenance="task:1"))
    with pytest.raises(MemoryPolicyError, match="memory_kind_invalid"):
        validate_fact(MemoryFact(key="k", value="v", provenance="task:1", kind="dream"))
    with pytest.raises(MemoryPolicyError, match="memory_source_invalid"):
        validate_fact(MemoryFact(key="k", value="v", provenance="task:1", source="model"))
    validate_fact(
        MemoryFact(key="k", value="v", provenance="user:telegram", kind="preference", source="user")
    )


def test_worker_limit_is_two():
    assert MAX_ACTIVE_WORKERS == 2


def test_llm_planner_prompt_and_parser():
    from jarvis.orchestration.llm_planner import (
        PlanProposalError,
        build_plan_prompt,
        parse_plan_response,
    )
    from jarvis.orchestration.planner import validate_plan

    prompt = build_plan_prompt(goal="rapikan gudang", constraints={"budget": "kecil"})
    assert "rapikan gudang" in prompt and "TANPA fence" in prompt
    good = (
        '```json\n[{"key": "t0", "title": "Daftar isi gudang", "role": "research", '
        '"acceptance": {"criteria": ["daftar lengkap"]}, "depends_on": []}]\n```'
    )
    plan = validate_plan(parse_plan_response(good))
    assert len(plan.nodes) == 1
    wrapped = (
        "Berikut rencananya:\n"
        '[{"key": "t0", "title": "Daftar isi gudang", "role": "research", '
        '"acceptance": {"criteria": ["daftar lengkap"]}, "depends_on": []}]\n'
        "Semoga membantu!"
    )
    assert len(validate_plan(parse_plan_response(wrapped)).nodes) == 1
    broken_fence = (
        "```json\n"
        '[{"key": "t0", "title": "Daftar isi gudang", "role": "research", '
        '"acceptance": {"criteria": ["daftar lengkap"]}, "depends_on": []}]'
    )
    assert len(validate_plan(parse_plan_response(broken_fence)).nodes) == 1
    for bad in ("bukan json", "[1, 2]", "[]", '{"key": "t0"}', "x" * 20001):
        try:
            nodes = parse_plan_response(bad)
            validate_plan(nodes)
        except (PlanProposalError, TaskError):
            continue
        raise AssertionError(f"proposal lolos: {bad[:40]}")
    with pytest.raises(PlanProposalError):
        build_plan_prompt(goal="")


def test_automation_schedule_parsing():
    from jarvis.automation.service import AutomationError, parse_schedule

    spec = parse_schedule("FREQ=DAILY;BYHOUR=8;BYMINUTE=30", "Asia/Jakarta")
    assert (spec.freq, spec.hour, spec.minute) == ("DAILY", 8, 30)
    spec = parse_schedule("FREQ=WEEKLY;BYDAY=MO,WE;BYHOUR=9;BYMINUTE=0", "UTC")
    assert spec.days == frozenset({0, 2})
    for bad in (
        "FREQ=HOURLY;BYHOUR=1;BYMINUTE=0",
        "FREQ=DAILY;BYHOUR=25;BYMINUTE=0",
        "FREQ=WEEKLY;BYHOUR=9;BYMINUTE=0",
        "FREQ=WEEKLY;BYDAY=XX;BYHOUR=9;BYMINUTE=0",
        "not-a-schedule",
    ):
        with pytest.raises(AutomationError):
            parse_schedule(bad, "UTC")
    with pytest.raises(AutomationError):
        parse_schedule("FREQ=DAILY;BYHOUR=8;BYMINUTE=0", "Mars/Olympus")


def test_automation_daily_occurrences_utc():
    from datetime import UTC, datetime, timedelta

    from jarvis.automation.service import occurrences_between, parse_schedule

    spec = parse_schedule("FREQ=DAILY;BYHOUR=8;BYMINUTE=0", "Asia/Jakarta")
    since = datetime(2026, 10, 8, 0, 0, tzinfo=UTC)
    until = since + timedelta(days=2)
    found = occurrences_between(spec, since, until)
    assert [d.isoformat() for d in found] == [
        "2026-10-08T01:00:00+00:00",
        "2026-10-09T01:00:00+00:00",
    ]


def test_automation_loop_parser_bounds():
    from jarvis.cli import parser

    args = parser().parse_args(
        ["automation-loop", "--owner-id", "00000000-0000-4000-8000-000000000001"]
    )
    assert (args.command, args.interval) == ("automation-loop", 300)
    args = parser().parse_args(
        [
            "automation-loop",
            "--owner-id",
            "00000000-0000-4000-8000-000000000001",
            "--interval",
            "30",
        ]
    )
    assert args.interval == 30
