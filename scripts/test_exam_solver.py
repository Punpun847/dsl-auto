"""ทดสอบ exam solver ใหม่ — login + เข้า course + เรียก _submit_exam"""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient  # noqa: E402


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()

        info = await client.page.evaluate(
            f"""async () => (await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}', {{credentials:'include'}})).json()"""
        )
        enroll_id = info.get("enroll_id")
        if not enroll_id:
            print("ต้อง enroll ก่อน")
            return

        print(f"course={course_id} enroll_id={enroll_id}")
        print("\n=== PRE-TEST SOLVER ===")
        await client._submit_exam(enroll_id, "pre-test")
        print("\n=== DONE ===")
        await client.page.wait_for_timeout(3_000)


if __name__ == "__main__":
    asyncio.run(main())
