from sqlalchemy import create_engine, text
e = create_engine("postgresql://gyso:gyso1234@localhost:5432/gyso_db")
with e.begin() as c:
    n = c.execute(text("UPDATE jobs SET status = 'failed' WHERE status IN ('running', 'queued')")).rowcount
    print(f"marked {n} jobs as failed")
