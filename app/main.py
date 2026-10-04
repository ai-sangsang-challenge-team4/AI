from fastapi import FastAPI

from app.api.v1.endpoints.ai import router as ai_router
from app.api.v1.endpoints.rag import router as rag_router


app = FastAPI(
    title="TeacherHub AI",
    version="0.1.0"
)

app.include_router(
    rag_router,
    prefix="/api/v1"
)

app.include_router(
    ai_router,
    prefix="/api/v1"
)


@app.get("/")
def root():
    return {"message": "TeacherHub AI"}