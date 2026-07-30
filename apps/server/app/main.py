from fastapi import FastAPI

from app.api.v1.health import router as health_router
from app.api.v1.me import router as me_router
from app.core.errors import register_exception_handlers

app = FastAPI(title="이음(E-um) MVP API")

register_exception_handlers(app)

app.include_router(health_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
