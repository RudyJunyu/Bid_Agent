"""ASGI entry point: uvicorn bid_agent.main:app."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Load configuration before importing application modules.
from bid_agent.core.settings import BUILD_VERSION, CORS_ORIGINS, ROOT_PATH
from bid_agent.infrastructure.database import init_database
from bid_agent.api.routes import documents, health, knowledge, projects


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_database()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title='Bid Agent', version=BUILD_VERSION, lifespan=lifespan, root_path=ROOT_PATH)
    if CORS_ORIGINS:
        app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS,
                           allow_credentials=False, allow_methods=['GET', 'POST', 'DELETE'],
                           allow_headers=['Content-Type'])
    for route in (health.router, documents.router, projects.router, knowledge.router):
        app.include_router(route)
    return app


app = create_app()
