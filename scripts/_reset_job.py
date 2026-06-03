"""Reset a stuck 'running' job back to 'queued' and re-dispatch it"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text

DB = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"
job_id = sys.argv[1] if len(sys.argv) > 1 else "6fe11d11-7077-4a7d-8c33-0ecf728d02df"

engine = create_engine(DB)
with engine.connect() as c:
    job = c.execute(text("SELECT id, status FROM jobs WHERE id=:j"), {"j": job_id}).fetchone()
    print(f"Current status: {job[1]}")

    # Reset to queued
    c.execute(text("UPDATE jobs SET status='queued', updated_at=NOW() WHERE id=:j"), {"j": job_id})
    c.commit()
    print(f"✅ Reset to 'queued'")

# Re-dispatch
from app.worker.celery_app import celery as celery_app
from app.worker.tasks import run_automation

result = run_automation.apply_async(args=[job_id])
print(f"✅ Re-dispatched! new task_id={result.id[:8]}...")
