"""Re-dispatch a stuck job back into Celery queue"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text

DB = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"
job_id = sys.argv[1] if len(sys.argv) > 1 else "6fe11d11-7077-4a7d-8c33-0ecf728d02df"

# Check current status
engine = create_engine(DB)
with engine.connect() as c:
    job = c.execute(text("SELECT id, status, updated_at FROM jobs WHERE id=:j"), {"j": job_id}).fetchone()
    print(f"Current status: {job[1]} (updated {job[2]})")

# Re-dispatch via Celery
from app.worker.celery_app import celery as celery_app
from app.worker.tasks import run_automation

print(f"Re-dispatching job {job_id[:8]}...")
result = run_automation.apply_async(args=[job_id], task_id=job_id)
print(f"✅ Dispatched! task_id={result.id[:8]}...")
print(f"   Check: python scripts/_check_job.py")
