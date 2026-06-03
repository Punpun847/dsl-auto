from sqlalchemy import create_engine, text
from datetime import datetime, timedelta, timezone

e = create_engine("postgresql://gyso:gyso1234@localhost:5432/gyso_db")
cutoff = datetime.now(timezone.utc) - timedelta(hours=1)

with e.connect() as c:
    rows = c.execute(text(
        "SELECT id, status, nid_hash, created_at, completed_at "
        "FROM jobs WHERE created_at > :cutoff ORDER BY created_at DESC"
    ), {"cutoff": cutoff}).fetchall()

    print(f"Jobs ใน 1 ชม.ล่าสุด: {len(rows)}")
    print()
    print(f"  {'job_id':<10} {'status':<10} {'certs':<8} {'created':<10}")
    print(f"  {'-'*10} {'-'*10} {'-'*8} {'-'*10}")
    n_done = 0
    n_run = 0
    for r in rows:
        certs_done = c.execute(text(
            "SELECT COUNT(*) FROM certificates WHERE job_id = :j AND pdf_path IS NOT NULL"
        ), {"j": str(r[0])}).scalar()
        total = c.execute(text(
            "SELECT COUNT(*) FROM certificates WHERE job_id = :j"
        ), {"j": str(r[0])}).scalar()
        created = r[3].strftime("%H:%M:%S")
        print(f"  {str(r[0])[:8]}.. {r[1]:<10} {certs_done}/{total:<6} {created}")
        if r[1] == "done":
            n_done += 1
        elif r[1] == "running":
            n_run += 1
    print(f"\nสรุป: done={n_done}, running={n_run}, total={len(rows)}")
