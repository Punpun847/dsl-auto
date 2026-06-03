"""Test exam solver สำหรับคอร์ส วางแผนลดหนี้มีออม สำหรับบัณฑิตยุคใหม่ เท่านั้น
usage: python scripts/test_debt_course.py <NID> <PWD>"""
import asyncio
import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
from app.worker.dsl_client import DSLClient

TARGET_KEYWORDS = ["วางแผนลดหนี้", "บัณฑิตยุคใหม่"]


async def main():
    nid, pwd = sys.argv[1], sys.argv[2]

    async with DSLClient(headless=False) as client:
        print(f"[1] login {nid[:6]}…")
        ok = await client.login(nid, pwd)
        if not ok:
            print(f"  login failed: {client.last_error}")
            return

        print("[2] SSO to SET")
        await client.goto_set()

        print("[3] หา course วางแผนลดหนี้มีออม…")
        courses = await client.fetch_courses()
        target = None
        for c in courses:
            title = c.get("title") or ""
            if any(kw in title for kw in TARGET_KEYWORDS):
                target = c
                break
        if not target:
            print(f"  ไม่เจอ — มี {len(courses)} คอร์สทั้งหมด:")
            for c in courses[:30]:
                print(f"    id={c.get('id'):>5} {(c.get('title') or '')[:70]}")
            return

        course_id = target["id"]
        enroll_id = target.get("enroll_id")
        print(f"  → course_id={course_id}, enroll_id={enroll_id}")
        print(f"  → title={target.get('title')}")

        if not enroll_id:
            data = await client.page.evaluate(
                f"async () => (await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}',{{credentials:'include'}})).json()"
            )
            enroll_id = data.get("enroll_id")
            print(f"  → enroll_id (จาก course API): {enroll_id}")
            if not enroll_id:
                print("  ไม่มี enroll_id — ต้องลงทะเบียนก่อน")
                return

        print(f"\n[4] รัน _submit_exam(exam) สำหรับ enroll_id={enroll_id}")
        await client._submit_exam(int(enroll_id), "exam")

        print("\n[5] ตรวจผลล่าสุด")
        ed = await client.page.evaluate(
            f"async () => (await fetch('/api/site/enroll/{enroll_id}',{{credentials:'include'}})).json()"
        )
        print(f"  exam_percentage      = {ed.get('exam_percentage')}")
        print(f"  post_test_percentage = {ed.get('post_test_percentage')}")
        print(f"  certificate_datetime = {ed.get('certificate_datetime')}")

        await client.page.wait_for_timeout(8000)


if __name__ == "__main__":
    asyncio.run(main())
