from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    display_name: str
    timezone: str
    status: str
    created_at: datetime


class TokenView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    label: str
    scopes: list[str]
    expires_at: datetime
    revoked_at: datetime | None
    last_used_at: datetime | None
    created_at: datetime


class AuditView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    action: str
    resource_id: UUID | None
    created_at: datetime
