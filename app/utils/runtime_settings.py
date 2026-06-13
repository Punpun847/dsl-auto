"""Runtime settings — ค่าที่แอดมินเปิด/ปิดได้สดจากหน้าเว็บ (เก็บใน Redis, ไม่ต้อง restart)
fallback ไปที่ค่าใน .env (settings) ถ้ายังไม่เคยตั้งค่า override
"""
from app.config import settings
from app.utils.redis_client import get_redis

FREE_MODE_KEY = "dsl:settings:free_mode"


async def get_free_mode() -> bool:
    """ค่า FREE_MODE ที่ใช้จริง: Redis override (ถ้ามี) → ไม่งั้น .env"""
    try:
        v = await get_redis().get(FREE_MODE_KEY)
        if v is not None:
            return v == "1"
    except Exception:
        pass
    return settings.free_mode


async def set_free_mode(on: bool) -> None:
    await get_redis().set(FREE_MODE_KEY, "1" if on else "0")
