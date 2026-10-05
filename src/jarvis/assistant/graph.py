"""ID-only LangGraph; PostgreSQL domain journal owns replay and authorization semantics."""

from typing import TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context

from jarvis.assistant.diagnostics import error_code, report_error
from jarvis.assistant.policy import PolicyError
from jarvis.assistant.router import RouterError


class FlowState(TypedDict):
    request_id: str
    action: str


class AssistantWorkflow:
    def __init__(self, repo, router, check_lock):
        self.repo, self.router, self.check_lock = repo, router, check_lock
        builder = StateGraph(FlowState)
        builder.add_node("guard_and_snapshot", self.guard)
        builder.add_node("route_and_dispatch", self.run)
        builder.add_node("offer_consent", self.offer)
        builder.add_edge(START, "guard_and_snapshot")
        builder.add_conditional_edges(
            "guard_and_snapshot", lambda s: s["action"], {"run": "route_and_dispatch", "end": END}
        )
        builder.add_conditional_edges(
            "route_and_dispatch", lambda s: s["action"], {"offer": "offer_consent", "end": END}
        )
        builder.add_edge("offer_consent", END)
        self.graph = builder.compile()

    async def guard(self, state):
        request_id = UUID(state["request_id"])
        if await self.repo.route_tool(request_id):
            return {"action": "end"}
        try:
            row = await self.repo.prepare(request_id)
        except PolicyError as exc:
            code = report_error(exc, phase="guard", kind="unknown", request_id=request_id)
            await self.repo.fail(request_id, code)
            row = None
        return {"action": "run" if row else "end"}

    async def run(self, state):
        request_id = UUID(state["request_id"])
        # Load immutable snapshot, never place it in graph state or traces.
        async with self.repo.db.tenant(self.repo.owner) as session:
            from jarvis.storage.models import AssistantRequest

            row = await session.get(AssistantRequest, request_id)
        kind = "premium" if row.status == "approved" else "free"
        phase = "plan"
        try:
            plan = await self.router.plan(self.repo.config, kind)
            await self.check_lock()
            phase = "dispatch"
            call_id = await self.repo.dispatch(request_id, plan)
        except (PolicyError, RouterError) as exc:
            code = report_error(exc, phase=phase, kind=kind, request_id=request_id)
            if kind == "free" and self.repo.config.premium_enabled:
                return {"action": "offer"}
            await self.repo.fail(request_id, code)
            return {"action": "end"}
        if call_id is None:
            return {"action": "end"}
        # Commit reservation before any external request. Crash after commit stays uncertain.
        await self.check_lock()
        try:
            result = await self.router.complete(plan, row.messages, row.data_class)
            error = None
        except RouterError as exc:
            result, error = None, exc
        except PolicyError:
            # This should have been caught before dispatch; never retry this attempt.
            result, error = None, RouterError("local_policy_error", uncertain=True)
        if error is not None:
            report_error(error, phase="complete", kind=kind, request_id=request_id)
        await self.check_lock()
        offer = await self.repo.finish(request_id, call_id, result, error)
        if offer and not self.repo.config.premium_enabled:
            # Preserve the free failure; probing a disabled premium route hid it before.
            await self.repo.fail(request_id, error_code(error))
            return {"action": "end"}
        return {"action": "offer" if offer else "end"}

    async def offer(self, state):
        request_id = UUID(state["request_id"])
        try:
            plan = await self.router.plan(self.repo.config, "premium")
            await self.check_lock()
            await self.repo.offer(request_id, plan)
        except (PolicyError, RouterError) as exc:
            reason = report_error(exc, phase="offer", kind="premium", request_id=request_id)
            await self.repo.fail(request_id, reason)
        return {"action": "end"}

    async def invoke(self, request_id):
        with tracing_context(enabled=False):
            return await self.graph.ainvoke(
                {"request_id": str(request_id), "action": "run"},
                config={"recursion_limit": 8, "callbacks": []},
            )
