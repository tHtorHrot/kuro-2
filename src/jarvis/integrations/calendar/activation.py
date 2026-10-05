"""Trusted Calendar activation factory.

This is the only composition point that turns deployment secrets into the
provider-backed Calendar specialist runtime.
"""

from dataclasses import dataclass, field
from uuid import UUID

from pydantic import SecretStr

from jarvis.agents.registry import AgentRegistry
from jarvis.integrations.calendar.agent import calendar_agent_spec, calendar_tool_specs
from jarvis.integrations.calendar.config import calendar_binding
from jarvis.integrations.calendar.google import GoogleCalendarProvider
from jarvis.integrations.calendar.oauth import GoogleOAuthTokenProvider
from jarvis.integrations.calendar.tools import calendar_handlers
from jarvis.tools.execution import ExecutionBroker
from jarvis.tools.journal import ActionJournal
from jarvis.tools.registry import ToolRegistry
from jarvis.tools.runtime import ToolRuntime
from jarvis.tools.scheduler import ActionScheduler


@dataclass(frozen=True)
class CalendarActivation:
    registry: ToolRegistry
    agents: AgentRegistry
    runtime: ToolRuntime
    journal: ActionJournal
    broker: ExecutionBroker
    scheduler: ActionScheduler
    provider: GoogleCalendarProvider = field(repr=False)


def activate_google_calendar(
    db,
    owner_id: UUID,
    *,
    client_id: SecretStr,
    client_secret: SecretStr,
    refresh_token: SecretStr,
    calendar_id: str = "primary",
    oauth_client=None,
    calendar_client=None,
) -> CalendarActivation:
    token_provider = GoogleOAuthTokenProvider(
        client_id, client_secret, refresh_token, client=oauth_client
    )
    provider = GoogleCalendarProvider(
        token_provider, calendar_id=calendar_id, client=calendar_client
    )
    registry = ToolRegistry(calendar_tool_specs())
    agents = AgentRegistry(registry)
    agents.register(calendar_agent_spec())
    handlers = calendar_handlers(provider)
    runtime = ToolRuntime(registry, handlers)
    journal = ActionJournal(
        db,
        owner_id,
        registry,
        executor_binding=calendar_binding(client_id, refresh_token, calendar_id),
    )
    broker = ExecutionBroker(journal, registry, handlers)
    scheduler = ActionScheduler(journal, broker)
    return CalendarActivation(registry, agents, runtime, journal, broker, scheduler, provider)
