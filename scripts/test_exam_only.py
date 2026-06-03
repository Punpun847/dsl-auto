"""Test exam solver ใหม่ — login + หา Macro Analysis + รัน _submit_exam อย่างเดียว
usage: python scripts/test_exam_only.py <NID> <PWD>"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient


async def main():
    nid, pwd = sys.argv[1], sys.argv[2]
    target_keywords = ["macro analysis", "Macro Analysis"]

    async with DSLClient(headless=False) as client:
        print(f"[1] login {nid[:6]}…")
        ok = await client.login(nid, pwd)
        if not ok:
            print(f"  login failed: {client.last_error}")
            return

        print("[2] SSO to SET")
        await client.goto_set()

        print("[3] หา course Macro Analysis")
        courses = await client.fetch_courses()
        target = None
        for c in courses:
            title = (c.get("title") or "").lower()
            if any(kw.lower() in title for kw in target_keywords):
                target = c
                break
        if not target:
            print(f"  ไม่เจอ — มี {len(courses)} คอร์ส:")
            for c in courses[:20]:
                print(f"    id={c['id']:>5} {c.get('title', '')[:60]}")
            return

        course_id = target["id"]
        enroll_id = target.get("enroll_id")
        print(f"  → course_id={course_id}, enroll_id={enroll_id}, title={target.get('title')}")

        if not enroll_id:
            # ดึง enroll_id จาก course API
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
        # ดึง enroll data ดู exam_percentage
        ed = await client.page.evaluate(
            f"async () => (await fetch('/api/site/enroll/{enroll_id}',{{credentials:'include'}})).json()"
        )
        print(f"  exam_percentage={ed.get('exam_percentage')}")
        print(f"  post_test_percentage={ed.get('post_test_percentage')}")
        print(f"  certificate_datetime={ed.get('certificate_datetime')}")

        await client.page.wait_for_timeout(8000)


if __name__ == "__main__":
    asyncio.run(main())
