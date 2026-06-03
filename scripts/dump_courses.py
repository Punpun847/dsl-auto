"""
Login + ดึงรายการ courses ทั้งหมดของ user แล้ว dump ออกมา (id, code, title, url)
ใช้สำหรับหา numeric course id ของคอร์สที่ต้องการ
รัน:
    python scripts/dump_courses.py <NID> <PWD>
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient  # noqa: E402

OUT = Path("/tmp/my_courses.json")


async def main():
    if len(sys.argv) < 3:
        print("usage: python scripts/dump_courses.py <NID> <PWD>")
        sys.exit(1)

    nid, pwd = sys.argv[1], sys.argv[2]

    async with DSLClient(headless=True) as client:
        print(f"[1/2] login as {nid[:6]}…")
        ok = await client.login(nid, pwd)
        if not ok:
            print(f"login failed: {client.last_error}")
            sys.exit(2)

        print("[2/2] fetch courses…")
        courses = await client.fetch_courses()

    OUT.write_text(json.dumps(courses, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT} — {len(courses)} courses")
    for c in courses:
        print(f"  id={c['id']:<10} code={c.get('code', ''):<12} hours={c.get('hours', 0):<5} {c.get('title', '')[:60]}")


if __name__ == "__main__":
    asyncio.run(main())
