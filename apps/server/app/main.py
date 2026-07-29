from fastapi import FastAPI

from app.api.v1.health import router as health_router

app = FastAPI(title="이음(E-um) MVP API")

app.include_router(health_router, prefix="/api/v1")
