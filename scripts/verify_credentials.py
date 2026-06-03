"""ตรวจสอบ credentials กยศ. ทีละหลายคน — ทดสอบ DSL login จริงโดยไม่รันคอร์ส

Usage:
    python scripts/verify_credentials.py accounts.csv

Format ของ accounts.csv (ไม่มี header):
    1234567890123,password1
    9876543210987,password2
    ...

ผลลัพธ์:
    ✅ 1234567890123 — login OK
    ❌ 9876543210987 — login failed: 401-RMS-AU20202
"""
import asyncio
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))

from dotenv import load_dotenv
load_dotenv()

from app.worker.dsl_client import DSLClient


async def check_one(nid: str, pwd: str) -> tuple[bool, str]:
    try:
        async with DSLClient(headless=True) as client:
            ok = await client.login(nid, pwd)
            if ok:
                return True, "login OK"
            return False, client.last_error or "login failed"
    except Exception as e:
        return False, str(e)


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/verify_credentials.py accounts.csv")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"❌ ไม่พบไฟล์ {csv_path}")
        sys.exit(1)

    rows = []
    with open(csv_path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                rows.append((row[0].strip(), row[1].strip()))

    print(f"📋 พบ {len(rows)} accounts — เริ่มตรวจสอบ...\n")

    ok_list, fail_list = [], []
    for i, (nid, pwd) in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {nid[:4]}***{nid[-3:]} ...", end=" ", flush=True)
        success, msg = await check_one(nid, pwd)
        if success:
            print(f"✅ {msg}")
            ok_list.append(nid)
        else:
            print(f"❌ {msg}")
            fail_list.append((nid, msg))

    print(f"\n{'═'*50}")
    print(f"✅ ผ่าน   : {len(ok_list)}/{len(rows)}")
    print(f"❌ ไม่ผ่าน: {len(fail_list)}/{len(rows)}")
    if fail_list:
        print("\nรายการที่ล้มเหลว:")
        for nid, reason in fail_list:
            print(f"  {nid} → {reason}")


if __name__ == "__main__":
    asyncio.run(main())
