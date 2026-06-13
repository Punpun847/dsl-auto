from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api import admin, admin_panel, auth, courses, jobs, payments, ws
from app.config import settings

app = FastAPI(title="GYSO Automation API", version="1.0.0")

# Rate limiter — ใช้ IP-based + Redis backend ผ่าน slowapi
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.redis_url)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

_cors_origins = settings.get_cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(payments.router, prefix="/payments", tags=["payments"])
app.include_router(courses.router, prefix="/courses", tags=["courses"])
app.include_router(ws.router, tags=["websocket"])
app.include_router(admin.router)
app.include_router(admin_panel.router)
app.include_router(auth.router)

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
UI_DIR = Path(__file__).parent.parent / "ui"


@app.get("/health")
async def health():
    """Health + runtime flags ที่ frontend ใช้แสดง UI ให้ตรง backend mode"""
    from app.utils.runtime_settings import get_free_mode
    return {
        "status": "ok",
        "free_mode": await get_free_mode(),
        "price_per_hour": 3,
    }


@app.get("/")
async def index():
    return FileResponse(UI_DIR / "index.html")


@app.get("/admin-panel")
async def admin_panel():
    return FileResponse(FRONTEND_DIR / "admin.html")
