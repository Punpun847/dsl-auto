"""ดึงรายการคอร์สที่ยังไม่ได้ทำจาก SET — ไม่ซ้ำกับที่ทำไปแล้ว

Usage:
    python scripts/_list_incomplete.py <NID> <PWD>
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "stubs"))
sys.stdout.reconfigure(encoding="utf-8")

from app.worker.dsl_client import DSLClient


async def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/_list_incomplete.py <NID> <PWD>")
        sys.exit(1)

    nid = sys.argv[1]
    pwd = sys.argv[2]

    print(f"กำลัง login SET สำหรับ {nid[:4]}***{nid[-3:]} ...")
    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        if not ok:
            print("❌ login ไม่ได้")
            return

        print("✅ login สำเร็จ — ดึงคอร์สที่ยังไม่ได้ทำ...")
        courses = await client.fetch_courses()

        if not courses:
            print("ไม่มีคอร์สที่ทำได้เลย (ทำครบแล้วหรือ fetch ไม่ได้)")
            return

        print(f"\n{'─'*60}")
        print(f"  คอร์สที่ยังไม่ได้ทำ: {len(courses)} คอร์ส")
        print(f"{'─'*60}")
        total_h = 0
        for c in courses:
            cid   = c.get("id", "?")
            h     = float(c.get("hours") or 1)
            title = c.get("title", "")[:45]
            total_h += h
            print(f"  [{cid:>5}]  {h:>4.1f}h  {title}")

        print(f"{'─'*60}")
        print(f"  รวม {len(courses)} คอร์ส = {total_h:.1f} ชม.")
        print(f"{'─'*60}")

        # แสดง course IDs สำหรับ copy ไปใช้
        ids = [str(c["id"]) for c in courses]
        print(f"\nCourse IDs: {ids}")


if __name__ == "__main__":
    asyncio.run(main())
