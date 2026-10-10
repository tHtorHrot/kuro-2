"""Independent Calendar completion outbox. Ambiguous sends are never recycled."""

from datetime import timedelta

from sqlalchemy import select, update

from jarvis.core.config import ConfigurationError
from jarvis.orchestration.calendar_tasks import task_valid
from jarvis.storage.models import AssistantState, CalendarNotification, CalendarTask, User

NOTIFICATION_AGE = timedelta(hours=24)


async def claim_notification(repo, session, now):
    from jarvis.interfaces.telegram.repository import MAX_ATTEMPTS, Delivery

    await session.execute(
        update(CalendarNotification)
        .where(
            CalendarNotification.owner_id == repo.config.owner_id,
            CalendarNotification.bot_id == repo.config.bot_id,
            CalendarNotification.delivery_status == "pending",
            CalendarNotification.created_at < now - NOTIFICATION_AGE,
        )
        .values(delivery_status="expired", reply_text=None)
    )
    row = await session.scalar(
        select(CalendarNotification)
        .where(
            CalendarNotification.owner_id == repo.config.owner_id,
            CalendarNotification.bot_id == repo.config.bot_id,
            CalendarNotification.delivery_status == "pending",
            CalendarNotification.next_attempt_at <= now,
        )
        .order_by(CalendarNotification.created_at, CalendarNotification.id)
        .with_for_update()
        .limit(1)
    )
    if row is None:
        return None
    task = await session.get(CalendarTask, row.task_id)
    state = await session.get(AssistantState, repo.config.owner_id)
    user, identity = await session.get(User, repo.config.owner_id), await repo.identity(session)
    if (
        not task
        or task.current_action_id != row.action_id
        or not await task_valid(session, task, state)
        or not user
        or user.status != "active"
        or not repo.identity_matches(identity)
        or row.chat_id != repo.config.sender_id
    ):
        row.delivery_status, row.reply_text = "blocked", None
        return None
    if row.attempts >= MAX_ATTEMPTS or not row.reply_text:
        row.delivery_status, row.reply_text = "failed", None
        return None
    row.attempts += 1
    row.delivery_status = "sending"
    return Delivery(0, row.chat_id, "assistant", row.attempts, row.reply_text, row.id)


async def finish_notification(repo, session, delivery, now, message_id, error):
    from jarvis.interfaces.telegram.repository import MAX_ATTEMPTS

    row = await session.get(CalendarNotification, delivery.notification_id)
    if (
        not row
        or row.bot_id != repo.config.bot_id
        or row.delivery_status != "sending"
        or row.attempts != delivery.attempt
    ):
        raise ConfigurationError("Calendar delivery claim was lost")
    if error is None and message_id is not None:
        row.delivery_status, row.telegram_message_id = "sent", message_id
    elif error is None or error.ambiguous:
        row.delivery_status = "uncertain"
    elif error.retryable and row.attempts < MAX_ATTEMPTS:
        delay = max(error.retry_after, min(2**row.attempts, 60))
        row.next_attempt_at = now + timedelta(seconds=delay)
        row.delivery_status = (
            "pending" if row.next_attempt_at < row.created_at + NOTIFICATION_AGE else "expired"
        )
    else:
        row.delivery_status = "failed"
    if row.delivery_status != "pending":
        row.reply_text = None
