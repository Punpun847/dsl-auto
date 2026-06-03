"""Auto-merge — เฝ้าดู job status ทุก 30 วินาที
พอ user ไหนเสร็จ (status=done) → merge PDF ทันที
"""
import hashlib
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = "postgresql://gyso:gyso1234@localhost:5432/gyso_db"
NAMES = {
    "1640101466032": "สุกฤษฎิ์",
    "1648900068680": "สุวารักษ์",
    "1640101459222": "สุวินชา",
    "1648900066814": "หยาดทิพย์",
    "1619600022022": "อรทัย",
    "1839400023112": "อริสรา",
    "1100703767981": "อังควิภา",
    "1629400034078": "อารีวรรณ",
    "1118400023746": "ธนัญชนก",
    "1570900116157": "อำนาจ",
    "1359200056038": "ศิริวรรณ",
    "1639900441802": "นันธิดา",
    "1239900367037": "วงศ์ศิริ",
    "1659902334752": "วนิดา",
    "1600501261772": "ศิรภัสสร",
    "1559600024387": "ชลณิสา",
}


def main():
    # Map nid → nid_hash
    nid_hash_map = {}
    for nid in NAMES.keys():
        h = hashlib.sha256(nid.encode()).hexdigest()
        nid_hash_map[h] = nid

    merged_set = set()  # NID ที่ merge แล้ว
    engine = create_engine(DB)
    print("👁️  เฝ้าดู jobs ทุก 30 วินาที — กด Ctrl+C ออก\n")

    while True:
        try:
            # หา user ที่มี smart_submit job (created > 14:37) status=done
            with engine.connect() as c:
                rows = c.execute(text(
                    "SELECT DISTINCT nid_hash FROM jobs "
                    "WHERE status = 'done' AND created_at > NOW() - INTERVAL '2 hours'"
                )).fetchall()

            for (nid_hash,) in rows:
                nid = nid_hash_map.get(nid_hash)
                if not nid or nid in merged_set:
                    continue
                name = NAMES.get(nid, nid)
                ts = datetime.now().strftime("%H:%M:%S")
                print(f"\n[{ts}] 🎉 {name} ({nid}) เสร็จแล้ว — กำลัง merge…")
                subprocess.run([
                    sys.executable, str(ROOT / "scripts" / "merge_new_certs.py"),
                    nid, "--days", "1"
                ], cwd=ROOT)
                merged_set.add(nid)

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"err: {e}")

        time.sleep(30)


if __name__ == "__main__":
    main()
