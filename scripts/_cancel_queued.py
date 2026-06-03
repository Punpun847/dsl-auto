"""ยกเลิก jobs ที่ status=queued ก่อน worker หยิบไปทำ"""
from sqlalchemy import create_engine, text
from app.worker.celery_app import celery

e = create_engine("postgresql://gyso:gyso1234@localhost:5432/gyso_db")
with e.connect() as c:
    queued = c.execute(text("SELECT id FROM jobs WHERE status = 'queued'")).fetchall()
    print(f"queued jobs: {len(queued)}")

# Revoke ทุก task ที่อยู่ใน celery queue
i = celery.control.inspect()
reserved = i.reserved() or {}
all_reserved = []
for worker, tasks in reserved.items():
    for t in tasks:
        all_reserved.append(t.get("id"))
print(f"reserved tasks: {len(all_reserved)}")

# Purge queue
celery.control.purge()
print("purged queue")

# Mark queued jobs as failed
with e.begin() as c:
    n = c.execute(text("UPDATE jobs SET status = 'failed' WHERE status = 'queued'")).rowcount
    print(f"marked {n} jobs as failed")
