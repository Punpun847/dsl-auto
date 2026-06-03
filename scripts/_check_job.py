"""Check job status, payment record, and Redis credentials"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import create_engine, text
import redis as redis_lib

DB = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"
job_id = "6fe11d11-7077-4a7d-8c33-0ecf728d02df"

engine = create_engine(DB)
with engine.connect() as c:
    # Check job
    job = c.execute(text("SELECT id, status, created_at, updated_at FROM jobs WHERE id=:j"), {"j": job_id}).fetchone()
    print(f"JOB: {job}")

    # Check payment
    pay = c.execute(text("SELECT id, verified, amount, created_at FROM payments WHERE job_id=:j"), {"j": job_id}).fetchone()
    print(f"PAYMENT: {pay}")

    # Check certs count
    certs = c.execute(text("SELECT COUNT(*) FROM certificates WHERE job_id=:j"), {"j": job_id}).fetchone()
    print(f"CERTS: {certs[0]}")

# Check Redis
rdb = redis_lib.Redis(host="localhost", port=6379, decode_responses=True)
nid_key = f"job:{job_id}:nid"
pwd_key = f"job:{job_id}:pwd"
nid_val = rdb.get(nid_key)
pwd_val = rdb.get(pwd_key)
print(f"Redis nid key exists: {nid_val is not None}")
print(f"Redis pwd key exists: {pwd_val is not None}")

# Check TTL
nid_ttl = rdb.ttl(nid_key)
pwd_ttl = rdb.ttl(pwd_key)
print(f"Redis nid TTL: {nid_ttl}s")
print(f"Redis pwd TTL: {pwd_ttl}s")
