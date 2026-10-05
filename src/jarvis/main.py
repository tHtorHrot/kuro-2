import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from prometheus_client import CollectorRegistry, Counter
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from jarvis import __version__
from jarvis.api.middleware import BoundaryMiddleware
from jarvis.api.routes import router
from jarvis.core.config import Settings, load_settings
from jarvis.core.errors import ApplicationError, UnsafeDatabaseRole
from jarvis.core.logging import configure_logging
from jarvis.storage.database import Database

log = logging.getLogger(__name__)


def problem(request: Request, status: int, code: str, detail: str):
    headers = {"WWW-Authenticate": "Bearer"} if status == 401 else {}
    return JSONResponse(
        {
            "type": "about:blank",
            "title": code,
            "status": status,
            "code": code,
            "detail": detail,
            "request_id": getattr(request.state, "request_id", None),
        },
        status_code=status,
        media_type="application/problem+json",
        headers=headers,
    )


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or load_settings()
    configure_logging(settings.log_level, settings.redacted_values())
    db = database or Database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            await db.verify_runtime_role()
        except UnsafeDatabaseRole:
            await db.close()
            raise
        except Exception as exc:
            # Keep liveness available during transient DB outage; readiness stays false.
            log.warning("database_unavailable_at_startup", extra={"error_type": type(exc).__name__})
        try:
            yield
        finally:
            await db.close()

    app = FastAPI(
        title="Personal Jarvis Foundation",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        redoc_url=None,
    )
    app.state.database = db
    app.state.settings = settings
    app.state.metrics_registry = CollectorRegistry()
    app.state.http_requests = Counter(
        "jarvis_http_requests_total",
        "Completed HTTP requests",
        ["method", "route", "status"],
        registry=app.state.metrics_registry,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(BoundaryMiddleware, settings=settings)
    app.include_router(router)

    @app.exception_handler(ApplicationError)
    async def application_error(request: Request, exc: ApplicationError):
        return problem(request, exc.status, exc.code, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        # Do not echo the submitted input, which might contain confidential text or tokens.
        return problem(request, 422, "validation_error", "Format permintaan tidak valid.")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return problem(request, exc.status_code, "http_error", "Permintaan tidak dapat diproses.")

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        log.error(
            "unhandled_error",
            extra={
                "request_id": getattr(request.state, "request_id", None),
                "error_type": type(exc).__name__,
            },
        )
        return problem(request, 500, "internal_error", "Terjadi kesalahan internal.")

    return app
