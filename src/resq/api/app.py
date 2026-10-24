"""FastAPI application factory and lifecycle management for RESQ Dev."""

from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from resq.config import Settings, get_settings
from resq.database import (
    get_engine,
    get_session_factory,
    init_db,
    startup_recovery,
)
from resq.api.middleware import RequestSizeLimitMiddleware
from resq.api.routes import router


def create_app(
    settings: Optional[Settings] = None,
    session_factory=None,
    engine=None,
    pipeline_override=None,
) -> FastAPI:
    """Creates and configures the FastAPI application for RESQ Dev.
    
    Invariants:
    1. Single-Process Model: Executes startup recovery for orphaned in-flight jobs.
    2. Zero CORS Exposure: Binds locally for Python clients; no browser CORS surface.
    3. Request Body Ceiling: Enforces ASGI request body ceiling (512 KiB).
    4. Sanitized Errors: Strips credentials and internal stack traces from API responses.
    """
    cfg = settings or get_settings()
    db_engine = engine or get_engine(cfg.database_url)
    db_session_factory = session_factory or get_session_factory(db_engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: Ensure database schema exists and recover interrupted jobs
        init_db(db_engine)
        with db_session_factory() as session:
            startup_recovery(session)
        yield
        # Shutdown
        db_engine.dispose()

    app = FastAPI(
        title="RESQ Dev Verification API",
        description="Human-Supervised Python Code Verification & Isolated Sandbox Repair Assistant",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store infrastructure instances in app.state
    app.state.settings = cfg
    app.state.engine = db_engine
    app.state.session_factory = db_session_factory
    app.state.pipeline = pipeline_override

    # 1. Enforce ASGI request body limit
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=cfg.max_request_body_bytes,
    )

    # 2. Register routers
    app.include_router(router)

    # 3. Sanitized error handlers preventing internal path/credential leaks
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": jsonable_encoder(exc.errors())},
        )

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        # Never leak host filesystem paths, tracebacks, or secrets
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "An internal server error occurred."},
        )

    return app


# Default module-level application instance for ASGI servers (e.g., uvicorn resq.api.app:app)
app = create_app()
