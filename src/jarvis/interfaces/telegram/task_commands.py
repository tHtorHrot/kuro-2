"""Telegram task commands — /goal, /tasks, /task.

Satu service untuk API dan Telegram (Bagian 7.1): progress root task tidak
mengunci satu active chat request. Dipanggil di dalam transaksi cursor/
receipt Telegram yang sama; tidak memanggil provider/LLM di sini.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from jarvis.storage.models import Task, TaskEvent


def _reply(receipt, text: str | None):
    """Mirror assistant.repository.set_reply semantics (lazy import avoids a cycle).

    delivery_status MUST become pending, otherwise the outbox claim() never
    picks the receipt up and the user gets silence despite a stored task.
    """
    from jarvis.assistant.repository import set_reply

    set_reply(receipt, text)


def _short(value) -> str:
    return str(value).replace("-", "")[:8]


def format_task_detail(task, *, children=(), excerpt=None, sources=None, document=None) -> str:
    """Detail /task murni: judul + status + anak + kutipan riset + versi dokumen."""
    lines = [f"{task.title} [{task.status}] — {_short(task.id)}"]
    kids = list(children)[:5]
    if kids:
        lines.append("Anak:")
        lines += [f"- {t.title[:60]} [{t.status}] — {_short(t.id)}" for t in kids]
    if excerpt:
        shown = str(excerpt)[:800]
        head = f"Hasil riset ({sources} sumber):" if sources else "Hasil riset:"
        lines.append(head + "\n" + shown)
    if document:
        lines.append(
            f"Dokumen: {document.get('path')} (versi {document.get('version')}, "
            f"sha {str(document.get('sha256') or '')[:8]})"
        )
    return "\n".join(lines)


async def _resolve_task(session, owner_id, ref):
    from uuid import UUID

    try:
        task_id = UUID(str(ref))
    except (ValueError, AttributeError, TypeError):
        task_id = None
    if task_id is not None:
        task = await session.get(Task, task_id)
        return task if task is not None and task.owner_id == owner_id else None
    prefix = str(ref or "").strip().lower().replace("-", "")
    if not 8 <= len(prefix) <= 32 or any(c not in "0123456789abcdef" for c in prefix):
        return None
    rows = (
        await session.scalars(
            select(Task).where(Task.owner_id == owner_id).order_by(Task.created_at).limit(50)
        )
    ).all()
    hits = [t for t in rows if str(t.id).replace("-", "").startswith(prefix)]
    return hits[0] if len(hits) == 1 else None


async def handle_task_command(session, owner_id, incoming, receipt) -> None:
    cmd, arg = incoming.command, (incoming.argument or "").strip()
    if cmd == "tasks":
        rows = (
            await session.scalars(
                select(Task)
                .where(
                    Task.owner_id == owner_id,
                    Task.status.in_(
                        ("queued", "running", "waiting_approval", "waiting_dependency", "uncertain")
                    ),
                )
                .order_by(Task.priority.desc(), Task.created_at)
                .limit(10)
            )
        ).all()
        if not rows:
            _reply(receipt, "Tidak ada task aktif. Kirim goal langsung, contoh: ringkas dokumen X.")
            return
        lines = [
            f"{n}. {t.title[:60]} [{t.status}] — {_short(t.id)}" for n, t in enumerate(rows, 1)
        ]
        _reply(receipt, "Task aktif:\n" + "\n".join(lines) + "\n\nDetail: /task <8 char>.")
        return
    if cmd == "task":
        task = await _resolve_task(session, owner_id, arg)
        if task is None:
            _reply(receipt, "Task tidak ditemukan. Cek 8 char di /tasks.")
            return
        kids = (
            await session.scalars(
                select(Task)
                .where(Task.owner_id == owner_id, Task.parent_id == task.id)
                .order_by(Task.created_at)
                .limit(5)
            )
        ).all()
        excerpt, sources, document = None, None, None
        event = await session.scalar(
            select(TaskEvent)
            .where(
                TaskEvent.owner_id == owner_id,
                TaskEvent.task_id == task.id,
                TaskEvent.event_type == "research.completed",
            )
            .order_by(TaskEvent.id.desc())
        )
        if event is not None and isinstance(event.payload, dict):
            excerpt = event.payload.get("excerpt")
            sources = event.payload.get("sources")
        doc_event = await session.scalar(
            select(TaskEvent)
            .where(
                TaskEvent.owner_id == owner_id,
                TaskEvent.task_id == task.id,
                TaskEvent.event_type == "documents.completed",
            )
            .order_by(TaskEvent.id.desc())
        )
        if doc_event is not None and isinstance(doc_event.payload, dict):
            document = {
                "path": doc_event.payload.get("path"),
                "version": doc_event.payload.get("version"),
                "sha256": doc_event.payload.get("sha256"),
            }
        _reply(
            receipt,
            format_task_detail(
                task, children=kids, excerpt=excerpt, sources=sources, document=document
            ),
        )
        return
    if cmd == "goal":
        if not arg or len(arg) > 2000:
            _reply(receipt, "Gunakan /goal TEKS (1–2000 karakter).")
            return
        # Idempotency per update Telegram: key dari update_id agar double
        # delivery tidak menggandakan task.
        key = f"tg:{incoming.update_id}"
        digest = hashlib.sha256(
            json.dumps({"goal": arg}, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        existing = await session.scalar(
            select(Task).where(Task.owner_id == owner_id, Task.client_request_key == key)
        )
        if existing is not None:
            _reply(receipt, f"Goal sudah diterima: {_short(existing.id)} [{existing.status}]")
            return
        root = Task(
            id=uuid4(),
            owner_id=owner_id,
            client_request_key=key,
            payload_hash=digest,
            title=arg[:120],
            goal=arg,
            role="planner",
            acceptance={"criteria": ["goal selesai dan lolos acceptance"]},
            plan_revision=1,
            status="queued",
        )
        root.root_id = root.id
        session.add(root)
        await session.flush()
        session.add(
            TaskEvent(
                owner_id=owner_id,
                task_id=root.id,
                event_type="goal.submitted",
                payload={"via": "telegram"},
            )
        )
        _reply(receipt, f"Goal diterima: {_short(root.id)}. Pantau: /task {_short(root.id)}")
        return
    _reply(receipt, "Perintah task tidak dikenali. Gunakan /help.")
