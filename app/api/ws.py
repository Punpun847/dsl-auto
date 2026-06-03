import json
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import AsyncSessionLocal
from app.models import Job
from app.models.user import User
from app.utils.redis_client import get_redis
from app.utils.security import decode_access_token

router = APIRouter()


async def _ws_authorize(db, job_id: str, token: Optional[str]) -> Optional[str]:
    """Return None ถ้า authorized, หรือ error message ถ้าไม่ผ่าน"""
    result = await db.execute(
        select(Job).where(Job.id == job_id).options(selectinload(Job.logs))
    )
    job = result.scalar_one_or_none()
    if not job:
        return "ไม่พบ job นี้"
    if job.user_id is None:
        return None  # legacy anonymous job — เปิดอ่าน
    if not token:
        return "งานนี้ต้องล็อกอินก่อน"
    payload = decode_access_token(token)
    if not payload:
        return "Token ไม่ถูกต้องหรือหมดอายุ"
    user_result = await db.execute(select(User).where(User.id == payload["sub"]))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        return "ไม่พบ user หรือถูก deactivate"
    if user.is_admin or str(user.id) == str(job.user_id):
        return None
    return "ไม่มีสิทธิ์ดูงานนี้"


@router.websocket("/ws/jobs/{job_id}")
async def job_ws(
    websocket: WebSocket,
    job_id: str,
    token: Optional[str] = Query(default=None),
):
    await websocket.accept()

    # ส่ง logs ที่มีอยู่แล้วใน DB ก่อน (กรณี reconnect) + auth check
    async with AsyncSessionLocal() as db:
        err = await _ws_authorize(db, job_id, token)
        if err:
            await websocket.send_json({"type": "err", "message": err})
            await websocket.close()
            return

        result = await db.execute(
            select(Job)
            .where(Job.id == job_id)
            .options(selectinload(Job.logs))
        )
        job = result.scalar_one_or_none()

    if not job:
        await websocket.send_json({"type": "err", "message": "ไม่พบ job นี้"})
        await websocket.close()
        return

    # ส่ง snapshot เริ่มต้น
    await websocket.send_json({
        "event": "snapshot",
        "status": job.status.value,
        "logs": [
            {
                "type": log.type,
                "message": log.message,
                "progress": log.progress,
                "ts": log.created_at.isoformat(),
            }
            for log in job.logs
        ],
    })

    # Subscribe Redis channel สำหรับ job นี้
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"job:{job_id}:logs")

    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue

            data = json.loads(message["data"])
            await websocket.send_json({"event": "log", **data})

            # ถ้า worker บอกว่าจบแล้ว ปิด connection
            if data.get("type") in ("done", "err"):
                break

    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe(f"job:{job_id}:logs")
        await pubsub.aclose()
