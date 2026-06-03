"""เปิด exam, capture API ทุกอันที่เกี่ยวข้อง — GET ข้อสอบ + POST submit + response เฉลย"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_BASE  # noqa: E402


async def main():
    nid, pwd, course_id, exam_type = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    # exam_type: pre-test | post-test | exam
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()

        info = await client.page.evaluate(f"""async () => (await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}', {{credentials:'include'}})).json()""")
        enroll_id = info.get("enroll_id")
        print(f"course={course_id} enroll_id={enroll_id} exam={exam_type}\n")

        captured = []
        out = Path("/tmp/exam_capture.json")
        def _flush():
            out.write_text(json.dumps(captured, ensure_ascii=False, indent=2))

        async def on_req(req):
            if "/api/site/" not in req.url:
                return
            captured.append({
                "method": req.method, "url": req.url,
                "body": req.post_data,
            })
            _flush()
            print(f">>> {req.method} {req.url}")
            if req.post_data:
                print(f"    BODY: {req.post_data[:300]}")

        async def on_resp(resp):
            if "/api/site/" not in resp.url:
                return
            try:
                txt = await resp.text()
                short = txt[:500]
            except Exception:
                txt, short = "", "<err>"
            print(f"<<< {resp.status} {resp.url}")
            print(f"    RESP: {short}\n")
            for c in reversed(captured):
                if c["url"] == resp.url and "response" not in c:
                    c["response"] = txt
                    c["status"] = resp.status
                    break
            _flush()

        client.page.on("request", on_req)
        client.page.on("response", on_resp)

        # ไปหน้า exam
        exam_url = f"{SET_BASE}/enroll/{enroll_id}/exam/{exam_type}"
        await client.page.goto(exam_url, wait_until="domcontentloaded", timeout=30_000)

        print("\n" + "=" * 60)
        print(f"📝 ทำตามนี้ใน browser:")
        print(f"   1. ตอบมั่วทุกข้อ → submit (ดูว่าไม่ผ่าน)")
        print(f"   2. กลับเข้า exam ใหม่ → ตอบใหม่ (สลับคำตอบ)")
        print(f"   3. submit อีกครั้ง")
        print(f"   4. รอสูงสุด 5 นาที — เลิกได้เลยถ้าครบ")
        print("=" * 60 + "\n")

        await client.page.wait_for_timeout(5 * 60 * 1000)

        out = Path("/tmp/exam_capture.json")
        out.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
        print(f"\n💾 save → {out} ({len(captured)} reqs)")


if __name__ == "__main__":
    asyncio.run(main())
