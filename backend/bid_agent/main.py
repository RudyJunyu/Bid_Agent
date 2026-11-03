"""ASGI entry point: uvicorn bid_agent.main:app."""
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Load configuration before importing application modules.
from bid_agent.core.settings import BUILD_VERSION, CORS_ORIGINS, ROOT_PATH
from bid_agent.infrastructure.database import init_database
from bid_agent.api.routes import (
    auth,
    bids,
    documents,
    health,
    integrations,
    knowledge,
    projects,
    requirements,
    reviews,
    stages,
    workspace,
)
from bid_agent.core.security import bootstrap_identity, legacy_admin
from bid_agent.repositories.platform import init_platform_schema, NotFoundError, ConflictError, ForbiddenError


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    init_platform_schema()
    bootstrap_identity()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title='Bid Agent', version=BUILD_VERSION, lifespan=lifespan, root_path=ROOT_PATH)
    if CORS_ORIGINS:
        app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                           allow_credentials=False, allow_methods=['GET', 'POST', 'PUT', 'DELETE'],
                           allow_headers=['Content-Type', 'X-CSRF-Token', 'Idempotency-Key'])
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(workspace.router)
    app.include_router(requirements.router)
    app.include_router(stages.router)
    app.include_router(bids.router)
    app.include_router(reviews.router)
    app.include_router(integrations.router)
    for route in (documents.router, projects.router, knowledge.router):
        app.include_router(route, dependencies=[Depends(legacy_admin)])

    async def repository_error(request: Request, exc: Exception):
        status = 404 if isinstance(exc, NotFoundError) else 403 if isinstance(exc, ForbiddenError) else 409
        return JSONResponse(status_code=status, content={'detail': str(exc)})
    for exception in (NotFoundError, ConflictError, ForbiddenError):
        app.add_exception_handler(exception, repository_error)
    return app


app = create_app()
