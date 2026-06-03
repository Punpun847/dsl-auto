from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery(
    "gyso",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Bangkok",
    task_track_started=True,
    task_acks_late=True,          # ack หลังจบงาน ไม่ใช่ตอนรับ
    worker_prefetch_multiplier=1, # 1 job ต่อ worker
)

# ── Celery Beat schedule ───────────────────────────────────────
# ต้อง start worker พร้อม flag: celery -A app.worker.celery_app.celery beat
celery.conf.beat_schedule = {
    "retry-pending-certs-every-15min": {
        "task": "retry_pending_certs",
        "schedule": crontab(minute="*/15"),
    },
    "cleanup-old-uploads-daily": {
        "task": "cleanup_old_uploads",
        "schedule": crontab(hour=3, minute=0),  # ตี 3 ทุกวัน
    },
}
