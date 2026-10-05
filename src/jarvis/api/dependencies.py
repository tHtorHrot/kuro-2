from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from jarvis.identity.service import Principal, authenticate


async def principal(request: Request) -> Principal:
    return await authenticate(request.app.state.database, request.headers.get("authorization"))


CurrentPrincipal = Annotated[Principal, Depends(principal)]


async def tenant_session(request: Request, actor: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    async with request.app.state.database.tenant(actor.owner_id) as session:
        yield session


TenantSession = Annotated[AsyncSession, Depends(tenant_session, scope="function")]
