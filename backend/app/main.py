from fastapi import FastAPI

from app.api import auth, health
from app.core.config import Settings, get_settings
from app.core.database import criar_engine, criar_sessionmaker
from app.core.errors import register_error_handlers
from app.core.requisicao import registrar_request_id


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs_url = None if settings.is_production else "/docs"
    app = FastAPI(
        title="CyberSec Saúde API",
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = criar_engine(settings)
    app.state.sessionmaker = criar_sessionmaker(app.state.engine)
    register_error_handlers(app)
    registrar_request_id(app)
    app.include_router(health.router)
    app.include_router(auth.router)
    return app
