"""ดู cert_datetime ของแต่ละ user ที่เพิ่งรัน — แยกใบใหม่ vs ใบเก่า"""
import hashlib
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"

# Cutoff — งานที่ทำในวันนี้ถือว่า "ใหม่"
NEW_THRESHOLD = datetime.now(timezone.utc) - timedelta(hours=3)


def main():
    engine = create_engine(DB)
    accounts_file = ROOT / "accounts.csv"
    with open(accounts_file, encoding="utf-8-sig") as f:
        nids = [line.split(",")[0].strip() for line in f if line.strip()]

    for nid in nids:
        h = hashlib.sha256(nid.encode()).hexdigest()
        with engine.connect() as c:
            # หา jobs ของ user นี้
            jobs = c.execute(text(
                "SELECT id FROM jobs WHERE nid_hash = :h ORDER BY created_at DESC LIMIT 5"
            ), {"h": h}).fetchall()
            if not jobs:
                continue

            # ดู logs ที่บอก certificate_datetime
            print(f"\n=== {nid} ===")
            new_count = 0
            old_count = 0
            for (jid,) in jobs:
                logs = c.execute(text(
                    "SELECT message FROM job_logs WHERE job_id = :j ORDER BY created_at"
                ), {"j": str(jid)}).fetchall()
                for (msg,) in logs:
                    # หา pattern "cert try X/3 → certificate_datetime=..."
                    m = re.search(r"certificate_datetime=(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})", msg or "")
                    if m:
                        try:
                            dt = datetime.fromisoformat(m.group(1).replace(" ", "T")).replace(tzinfo=timezone.utc)
                            if dt > NEW_THRESHOLD:
                                new_count += 1
                            else:
                                old_count += 1
                        except Exception:
                            pass
            print(f"  certs ใหม่ (รันวันนี้): {new_count}")
            print(f"  certs เก่า (ทำมาก่อน): {old_count}")


if __name__ == "__main__":
    main()
