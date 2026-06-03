"""Quick status check"""
from sqlalchemy import create_engine, text

e = create_engine("postgresql://gyso:gyso1234@localhost:5432/gyso_db")
with e.connect() as c:
    rows = c.execute(text(
        "SELECT id, status, created_at, completed_at FROM jobs ORDER BY created_at DESC LIMIT 3"
    )).fetchall()
    for r in rows:
        print(f"job: {str(r[0])[:8]}... | status: {r[1]} | created: {r[2]} | done: {r[3]}")
        logs = c.execute(text(
            "SELECT type, message, created_at FROM job_logs WHERE job_id = :jid ORDER BY created_at DESC LIMIT 15"
        ), {"jid": str(r[0])}).fetchall()
        for l in reversed(logs):
            ts = l[2].strftime("%H:%M:%S")
            print(f"  [{ts}] [{l[0]}] {l[1]}")
        # cert
        certs = c.execute(text(
            "SELECT course_id, pdf_path FROM certificates WHERE job_id = :jid"
        ), {"jid": str(r[0])}).fetchall()
        if certs:
            print(f"  certs: {len(certs)} ใบ")
            for ct in certs:
                print(f"    course {ct[0]} → {ct[1] or 'pending'}")
        print()
