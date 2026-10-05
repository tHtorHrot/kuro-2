"""Calendar provider boundary and Stage 4 reference specialist."""

from jarvis.integrations.calendar.activation import CalendarActivation, activate_google_calendar
from jarvis.integrations.calendar.agent import CALENDAR_AGENT, calendar_tool_specs
from jarvis.integrations.calendar.google import GoogleCalendarProvider
from jarvis.integrations.calendar.oauth import GoogleOAuthTokenProvider
from jarvis.integrations.calendar.provider import CalendarProvider, CalendarProviderError
from jarvis.integrations.calendar.service import CalendarCommandResult, CalendarService
from jarvis.integrations.calendar.tools import calendar_handlers

__all__ = [
    "CALENDAR_AGENT",
    "CalendarActivation",
    "CalendarCommandResult",
    "CalendarProvider",
    "CalendarProviderError",
    "CalendarService",
    "GoogleCalendarProvider",
    "GoogleOAuthTokenProvider",
    "activate_google_calendar",
    "calendar_handlers",
    "calendar_tool_specs",
]
