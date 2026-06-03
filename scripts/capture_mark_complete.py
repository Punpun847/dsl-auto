"""เปิด browser, login, ไปที่หน้า course landing แล้วให้ user เล่นวิดีโอ 1 ตัวจริงๆจนจบ
script จะ capture ทุก POST/PUT/PATCH ที่ออก แล้วบันทึกลง /tmp/mark_capture.json
ใช้:
    python3 scripts/capture_mark_complete.py <nid> <pwd> <course_id>
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_BASE  # noqa: E402


OUT_PATH = Path("/tmp/mark_capture.json")


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()

        # ดึง enroll_id
        info = await client.page.evaluate(f"""async () => (await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}', {{credentials:'include'}})).json()""")
        enroll_id = info.get("enroll_id")
        print(f"course={course_id} enroll_id={enroll_id}")

        # ไปหน้า course landing (ให้ user เห็น list topic + click เอง)
        await client.page.goto(
            f"{SET_BASE}/enroll/{enroll_id}",
            wait_until="domcontentloaded", timeout=30_000,
        )

        captured = []
        async def on_request(req):
            if "/api/site/" not in req.url:
                return
            if req.method == "GET":
                return  # ไม่สน GET
            entry = {
                "method": req.method,
                "url": req.url,
                "headers": {k: v for k, v in req.headers.items()
                            if k.lower() in ("content-type", "x-xsrf-token", "x-requested-with")},
                "body": req.post_data,
            }
            captured.append(entry)
            print(f"\n>>> {req.method} {req.url}")
            print(f"    BODY: {req.post_data}")

        async def on_response(resp):
            if "/api/site/" not in resp.url:
                return
            if resp.request.method == "GET":
                return
            try:
                txt = await resp.text()
                txt = txt[:300]
            except Exception:
                txt = "<err>"
            print(f"<<< {resp.status} {resp.url}")
            print(f"    RESP: {txt}")
            # append to last matching entry
            for c in reversed(captured):
                if c["url"] == resp.url and "response" not in c:
                    c["response_status"] = resp.status
                    c["response_body"] = txt
                    break

        client.page.on("request", on_request)
        client.page.on("response", on_response)

        # บอก user ทำอะไร
        print("\n" + "=" * 60)
        print("📝 ตอนนี้ให้คุณ:")
        print("   1. คลิกเข้า topic ที่ยังไม่เสร็จ (ใน browser ที่เปิดอยู่)")
        print("   2. เล่นวิดีโอจนจบ — หรือเล่น+seek ไปท้ายสุด")
        print("   3. รอให้หน้า refresh / topic mark เป็น 100%")
        print("   4. รอสูงสุด 5 นาที — script จะ save ทุก POST ที่ออก")
        print("=" * 60 + "\n")

        await client.page.wait_for_timeout(5 * 60 * 1000)

        OUT_PATH.write_text(json.dumps(captured, ensure_ascii=False, indent=2))
        print(f"\n💾 บันทึก {len(captured)} requests → {OUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
