from dataclasses import dataclass
from enum import StrEnum


class DataClass(StrEnum):
    PUBLIC = "public"
    PERSONAL = "personal"
    RESTRICTED = "restricted"


class RouteDecision(StrEnum):
    ELIGIBLE_FREE = "eligible_free"
    APPROVAL_REQUIRED = "approval_required"
    DENIED = "denied"


@dataclass(frozen=True)
class EndpointPolicy:
    # Unknown policies default to rejection, even for a free model.
    training_allowed: bool | None = None
    zero_data_retention: bool | None = None
    paid: bool | None = True


def route_decision(data_class: DataClass, endpoint: EndpointPolicy) -> RouteDecision:
    """Eligibility only. This phase has no provider call or approval consumption."""
    if data_class not in (DataClass.PUBLIC, DataClass.PERSONAL):
        return RouteDecision.DENIED
    if endpoint.training_allowed is not False or endpoint.zero_data_retention is not True:
        return RouteDecision.DENIED
    if endpoint.paid is True:
        return RouteDecision.APPROVAL_REQUIRED
    if endpoint.paid is False:
        return RouteDecision.ELIGIBLE_FREE
    return RouteDecision.DENIED


def cloud_request_constraints() -> dict[str, object]:
    """Future adapter must also enforce account settings, provider allowlist and plugins."""
    return {
        "provider": {"data_collection": "deny", "zdr": True, "require_parameters": True},
        "plugins": [],
    }
