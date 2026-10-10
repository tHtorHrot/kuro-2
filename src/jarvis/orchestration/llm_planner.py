"""LLM planner proposal — prompt builder + strict parser.

Model hanya MENGUSULKAN plan; `validate_plan()` yang menentukan apakah
proposal menjadi state. Output model tidak pernah menjadi SQL/state
authority. Modul ini TIDAK memanggil provider: live call memakai jalur
chat approved (budget/consent/ledger). Preview prompt via CLI, uji live
via /ask, validasi via parser ini.
"""

from __future__ import annotations

import json

from jarvis.agents.roles import ALLOWED_ROLES

MAX_PROPOSAL_CHARS = 20000
MAX_GOAL_CHARS = 2000


class PlanProposalError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def build_plan_prompt(*, goal: str, constraints: dict | None = None) -> str:
    if not goal or not goal.strip() or len(goal) > MAX_GOAL_CHARS:
        raise PlanProposalError("goal_invalid")
    safe_constraints = constraints if isinstance(constraints, dict) else {}
    roles = ", ".join(sorted(ALLOWED_ROLES - {"planner"}))
    role_docs = (
        "research (mencari/membaca sumber informasi), knowledge (mengelola "
        "dokumen/basis pengetahuan), data (menghitung/menganalisis angka), "
        "coding (menulis/mengubah program), communication (menulis pesan/laporan)."
    )
    return (
        "Susun rencana kerja terstruktur untuk goal berikut. Balas HANYA "
        "dengan JSON array mentah, TANPA fence ```json, TANPA kalimat pembuka, "
        "TANPA penjelasan sesudah.\n"
        f"Goal: {goal.strip()}\n"
        f"Batasan: {json.dumps(safe_constraints, ensure_ascii=False)[:2000]}\n"
        "Aturan:\n"
        "- Maksimal 20 task, depth dependensi maksimal 2 (rantai A→B→C sudah "
        "2; jangan A→B→C→D), tanpa cycle.\n"
        "- Pilih role sesuai SIFAT pekerjaan. " + role_docs + "\n"
        "- Setiap task: key unik (t0, t1, ...), title <=120 karakter, "
        f"role salah satu dari: {roles}.\n"
        "- acceptance wajib berisi criteria yang bisa diperiksa.\n"
        "- depends_on hanya berisi key yang ada; [] bila independen.\n"
        "- cost_ceiling_usd angka 0..1000.\n"
        'Contoh: [{"key": "t0", "title": "Kumpulkan sumber", '
        '"role": "research", "acceptance": {"criteria": ["3 sumber '
        'dengan provenance"]}, "depends_on": [], "cost_ceiling_usd": 1.0}]'
    )


def _extract_json(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise PlanProposalError("proposal_empty")
    if len(text) > MAX_PROPOSAL_CHARS:
        raise PlanProposalError("proposal_too_large")
    body = text.strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if len(lines) < 3 or not lines[-1].strip().startswith("```"):
            raise PlanProposalError("proposal_fence_invalid")
        body = "\n".join(lines[1:-1])
    return body


def _candidate_bodies(text: str) -> list[str]:
    """Coba beberapa ekstraksi; validasi ketat tetap di validate_plan().
    Fallback bracket hanya menolong format, tidak melonggarkan aturan."""
    if not isinstance(text, str) or not text.strip():
        raise PlanProposalError("proposal_empty")
    if len(text) > MAX_PROPOSAL_CHARS:
        raise PlanProposalError("proposal_too_large")
    bodies: list[str] = []
    try:
        bodies.append(_extract_json(text))
    except PlanProposalError:
        pass
    stripped = text.strip()
    start, end = stripped.find("["), stripped.rfind("]")
    if 0 <= start < end:
        sliced = stripped[start : end + 1]
        if sliced not in bodies:
            bodies.append(sliced)
    return bodies


def parse_plan_response(text: str) -> list[dict]:
    """Parse longgar, validasi ketat di validate_plan(). Bentuk dasar dicek
    di sini agar error model mudah dibedakan dari error validasi."""
    errors: list[str] = []
    for body in _candidate_bodies(text):
        try:
            data = json.loads(body, parse_float=float)
        except ValueError as exc:
            errors.append(f"proposal_not_json:{exc}")
            continue
        try:
            return _check_shape(data)
        except PlanProposalError as exc:
            errors.append(exc.code)
    raise PlanProposalError(errors[0].split(":")[0] if errors else "proposal_not_json")


def _check_shape(data) -> list[dict]:
    if not isinstance(data, list) or not data:
        raise PlanProposalError("proposal_not_list")
    for node in data:
        if not isinstance(node, dict):
            raise PlanProposalError("proposal_node_invalid")
        if not isinstance(node.get("key"), str) or not isinstance(node.get("title"), str):
            raise PlanProposalError("proposal_node_invalid")
        if node.get("role") not in ALLOWED_ROLES:
            raise PlanProposalError("proposal_role_invalid")
        if not isinstance(node.get("acceptance"), dict):
            raise PlanProposalError("proposal_acceptance_invalid")
    return data


_REPAIR_HINTS = {
    "plan_depth_exceeded": " Rantai terlalu dalam: gabungkan task berurutan "
    "menjadi satu, atau buat task paralel langsung dari awal (depends_on []).",
    "plan_cycle_rejected": " Ada cycle dependensi: hapus salah satu depends_on.",
    "plan_self_dependency": " Task tidak boleh bergantung pada dirinya sendiri.",
    "plan_unknown_dependency": " depends_on hanya boleh berisi key yang ada.",
    "plan_unknown_role": " Pakai role yang sesuai sifat pekerjaan.",
    "plan_task_count_invalid": " Kurangi jumlah task menjadi maksimal 20.",
    "proposal_fence_invalid": " Balas HANYA JSON array: tanpa kalimat pembuka, "
    "tanpa penjelasan sesudah, fence ```json utuh bila dipakai.",
    "proposal_not_json": " Balas HANYA JSON array yang valid, tanpa teks lain.",
    "proposal_not_list": " Balas dengan JSON array (daftar task), bukan objek.",
}


async def propose_plan(
    db,
    owner,
    root_id,
    *,
    router,
    endpoint_plan: dict,
    worker: str = "planner-auto",
    max_attempts: int = 2,
) -> dict:
    """Usulkan plan via model, validasi ketat, buat subtasks. Maksimal 1
    repair untuk validation failure; provider ambiguity TIDAK di-retry.
    Router hanya dipanggil lewat interface complete() yang sudah
    budget/ledger-aware di sisi dispatch/finish."""
    from sqlalchemy import select

    from jarvis.agents.manager import claim_task, finish_run
    from jarvis.assistant.policy import SYSTEM_PROMPT
    from jarvis.assistant.router import RouterError
    from jarvis.orchestration.planner import validate_plan
    from jarvis.orchestration.task_inference import dispatch_task_call, finish_task_call
    from jarvis.orchestration.task_manager import create_plan_tasks, mark_task
    from jarvis.storage.models import Task

    if not 1 <= max_attempts <= 3:
        raise PlanProposalError("max_attempts_invalid")
    async with db.tenant(owner) as session:
        root = await session.get(Task, root_id)
        if root is None or root.owner_id != owner:
            raise PlanProposalError("root_not_found")
        goal = (root.goal or root.title or "").strip()
        if not goal:
            raise PlanProposalError("goal_empty")
        existing = await session.scalar(
            select(Task.id).where(Task.owner_id == owner, Task.parent_id == root.id).limit(1)
        )
        if existing is not None:
            raise PlanProposalError("plan_exists")
    feedback = ""
    attempts = 0
    while True:
        run = await claim_task(db, owner, worker_instance=worker, roles=["planner"])
        if run is None:
            raise PlanProposalError("no_worker_slot")
        try:
            call_id = await dispatch_task_call(
                db, owner, run_id=run.id, plan=endpoint_plan, kind="free"
            )
        except Exception as exc:
            try:
                await finish_run(
                    db, owner, run.id, run.lease_token, "failed", error_code=type(exc).__name__[:80]
                )
            except Exception:
                pass
            raise
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_plan_prompt(goal=goal) + feedback},
        ]
        try:
            completion = await router.complete(endpoint_plan, messages)
        except RouterError as exc:
            await finish_task_call(db, owner, call_id=call_id, error=exc)
            try:
                await finish_run(
                    db,
                    owner,
                    run.id,
                    run.lease_token,
                    "failed",
                    error_code=getattr(exc, "kind", "provider_error")[:80],
                )
            except Exception:
                pass
            raise PlanProposalError(f"provider_{getattr(exc, 'kind', 'error')}") from None
        await finish_task_call(db, owner, call_id=call_id, result=completion)
        try:
            nodes = parse_plan_response(completion.content)
            validate_plan(nodes)
        except Exception as exc:
            code = getattr(exc, "code", "plan_invalid")
            try:
                await finish_run(
                    db, owner, run.id, run.lease_token, "failed", error_code=str(code)[:80]
                )
            except Exception:
                pass
            attempts += 1
            if attempts >= max_attempts:
                try:
                    await mark_task(db, owner, root_id, "failed", error_code=str(code)[:80])
                except Exception:
                    pass
                raise PlanProposalError(f"plan_rejected_{code}") from None
            feedback = (
                f"\nUsulan sebelumnya DITOLAK validator ({code})."
                + _REPAIR_HINTS.get(str(code), "")
                + " Perbaiki minimal dan balas HANYA JSON array."
            )
            continue
        try:
            kids = await create_plan_tasks(db, owner, root_id, nodes)
        except Exception as exc:
            try:
                await finish_run(
                    db, owner, run.id, run.lease_token, "failed", error_code=type(exc).__name__[:80]
                )
            except Exception:
                pass
            raise
        try:
            await finish_run(db, owner, run.id, run.lease_token, "succeeded")
        except Exception:
            pass
        return {
            "task_id": str(root_id),
            "subtasks": [str(k.id) for k in kids],
            "attempts": attempts + 1,
            "repair_used": attempts > 0,
        }
