from fastapi import FastAPI

from app.api.v1.endpoints.ai import router as ai_router
from app.api.v1.endpoints.rag import router as rag_router
from app.core.operational_logging import OperationalMiddleware, configure_operational_logging


def create_app():
    configure_operational_logging()
    application = FastAPI(title="TeacherHub AI", version="0.1.0")
    application.add_middleware(OperationalMiddleware)
    application.include_router(rag_router, prefix="/api/v1")
    application.include_router(ai_router, prefix="/api/v1")

    @application.get("/")
    def root():
        return {"message": "TeacherHub AI"}

    return application


app = create_app()
