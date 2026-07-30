from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.bootstrap import router as bootstrap_router
from app.api.v1.health import router as health_router
from app.api.v1.home import router as home_router
from app.api.v1.me import router as me_router
from app.api.v1.plan_blocks import router as plan_blocks_router
from app.core.errors import register_exception_handlers

app = FastAPI(title="이음(E-um) MVP API")

DEV_ALLOWED_ORIGINS = [
    "http://localhost:8081",
    "http://localhost:8082",
    "http://127.0.0.1:8081",
    "http://127.0.0.1:8082",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=DEV_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(health_router, prefix="/api/v1")
app.include_router(me_router, prefix="/api/v1")
app.include_router(home_router, prefix="/api/v1")
app.include_router(plan_blocks_router, prefix="/api/v1")
app.include_router(bootstrap_router, prefix="/api/v1")
