"""ลิสต์คอร์ส SETStudentLoan ที่ user มีสิทธิ์เข้า"""
import asyncio
import sys
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(message)s')

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "stubs"))

from app.worker.dsl_client import DSLClient


async def main():
    nid, pwd = sys.argv[1], sys.argv[2]
    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        if not ok:
            print(f"login fail: {client.last_error}")
            return

        courses = await client.fetch_courses()
        print(f"\n=== {len(courses)} courses ===\n")
        print(f"{'ID':>6}  {'Hr':>4}  Title")
        print("-" * 70)
        for c in courses:
            cid = c.get('id', '?')
            title = (c.get('title') or '')[:55]
            hours = c.get('hours', '-')
            print(f"  {cid:>5}  {hours:>4}  {title}")


if __name__ == "__main__":
    asyncio.run(main())
