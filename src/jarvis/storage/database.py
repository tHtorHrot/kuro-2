from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from jarvis.core.config import Settings
from jarvis.core.errors import UnsafeDatabaseRole

SCHEMA_REVISION = "0015_memory_kinds"
TENANT_TABLES = (
    "users",
    "api_tokens",
    "pairing_codes",
    "external_identities",
    "audit_events",
    "telegram_state",
    "telegram_receipts",
    "assistant_state",
    "profile_memory",
    "assistant_requests",
    "conversation_messages",
    "llm_calls",
    "knowledge_state",
    "documents",
    "document_chunks",
    "tool_actions",
    "tool_grants",
    "calendar_tasks",
    "calendar_notifications",
    "tasks",
    "task_dependencies",
    "task_runs",
    "artifacts",
    "task_events",
    "automation_definitions",
    "automation_runs",
)


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_async_engine(
            settings.database_url.get_secret_value(),
            echo=False,
            hide_parameters=True,
            pool_pre_ping=True,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=5,
            connect_args={"connect_timeout": 5},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def tenant(self, owner_id: UUID) -> AsyncIterator[AsyncSession]:
        """SET LOCAL lasts only for this transaction; no pooled tenant leakage."""
        if not isinstance(owner_id, UUID):
            raise TypeError("owner_id must be a UUID")
        async with self.sessions.begin() as session:
            await session.execute(
                text("SELECT set_config('jarvis.owner_id', :owner_id, true)"),
                {"owner_id": str(owner_id)},
            )
            await session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": str(self.settings.db_statement_timeout_ms)},
            )
            yield session

    async def verify_runtime_role(self) -> None:
        async with self.engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, "
                        "rolreplication "
                        "FROM pg_roles WHERE rolname = current_user"
                    )
                )
            ).one()
            if row.rolname != "jarvis_app" or any(row[1:]):
                raise UnsafeDatabaseRole("Runtime requires the unprivileged jarvis_app role")
            owns = await conn.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n "
                    "ON c.relnamespace = n.oid WHERE n.nspname = 'app' "
                    "AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname=current_user))"
                )
            )
            if owns:
                raise UnsafeDatabaseRole("Runtime must not own application tables")
            membership = await conn.scalar(
                text(
                    "SELECT EXISTS(SELECT 1 FROM pg_auth_members "
                    "WHERE member = (SELECT oid FROM pg_roles WHERE rolname=current_user))"
                )
            )
            if membership:
                raise UnsafeDatabaseRole("Runtime must not be a member of other database roles")

    async def ready(self) -> bool:
        await self.verify_runtime_role()
        async with self.engine.connect() as conn:
            revision = await conn.scalar(
                text("SELECT version_num FROM public.jarvis_schema_version")
            )
            if revision != SCHEMA_REVISION:
                return False
            rows = (
                await conn.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                        "FROM pg_class c JOIN pg_namespace n ON c.relnamespace=n.oid "
                        "WHERE n.nspname='app' AND c.relkind='r'"
                    )
                )
            ).all()
            secured = {name for name, rls, force in rows if rls and force}
            return set(TENANT_TABLES).issubset(secured)

    async def close(self) -> None:
        await self.engine.dispose()
