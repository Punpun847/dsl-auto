import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job_log import JobLog
from app.utils.redis_client import get_redis


async def log_job(
    db: AsyncSession,
    job_id: str,
    type: str,
    message: str,
    progress: Optional[str] = None,
    *,
    redis=None,
) -> None:
    """บันทึก log + publish ไป Redis pub/sub

    redis: ส่ง client มาเองได้ (ใน Celery worker) — กัน "attached to a different loop"
    ถ้าไม่ส่ง → ใช้ singleton จาก get_redis() (สำหรับ FastAPI request scope)
    """
    now = datetime.now(timezone.utc)

    # บันทึกลง DB
    entry = JobLog(
        job_id=job_id,
        type=type,
        message=message[:500],
        progress=progress,
        created_at=now,
    )
    db.add(entry)
    await db.commit()

    # Publish ไป WebSocket clients ผ่าน Redis
    r = redis if redis is not None else get_redis()
    payload = json.dumps({
        "type": type,
        "message": message,
        "progress": progress,
        "ts": now.isoformat(),
    })
    await r.publish(f"job:{job_id}:logs", payload)
