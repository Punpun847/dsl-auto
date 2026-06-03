"""เปิดให้ user ทำ survey ของ course 923 + capture API call จริง"""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient, SET_BASE


OUT = Path("/tmp/survey_real.json")


async def main():
    async with DSLClient(headless=False) as client:
        await client.login("1100201764358", "Poonnapob200432")
        await client.goto_set()
        info = await client.page.evaluate(
            'async () => (await fetch("/api/site/groups/SETStudentLoan/courses/923",{credentials:"include"})).json()'
        )
        eid = info.get("enroll_id")
        await client.page.goto(f"{SET_BASE}/enroll/{eid}/summary",
                                wait_until="domcontentloaded", timeout=30000)
        await client.page.wait_for_timeout(3000)
        # expand accordion + scroll to survey
        await client.page.evaluate("""() => {
            document.querySelectorAll('.collapse').forEach(c => {
                c.classList.add('show');
                c.style.display = 'block';
                c.style.height = 'auto';
            });
            const form = document.querySelector('#survey-form');
            if (form) form.scrollIntoView({behavior:'smooth', block:'center'});
        }""")

        captured = []
        def flush():
            OUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))

        async def on_req(r):
            if "elearning.set.or.th" not in r.url or "analytics" in r.url or "google" in r.url:
                return
            entry = {"method": r.method, "url": r.url, "body": r.post_data}
            captured.append(entry)
            flush()
            print(f"\n>>> {r.method} {r.url[:120]}")
            if r.post_data:
                print(f"    BODY: {r.post_data[:300]}")

        async def on_resp(r):
            if "elearning.set.or.th" not in r.url or "analytics" in r.url:
                return
            try:
                txt = (await r.text())[:400]
            except: txt = "<err>"
            print(f"<<< {r.status} {r.url[:80]}\n    RESP: {txt}")
            for c in reversed(captured):
                if c["url"] == r.url and "status" not in c:
                    c["status"] = r.status; c["response"] = txt
                    break
            flush()

        client.page.on("request", on_req)
        client.page.on("response", on_resp)

        print("\n" + "="*60)
        print("📝 ทำ survey ของ course 923:")
        print("   1. ในหน้าควรเห็น 'แบบสอบถาม' พร้อม radio")
        print("   2. ตอบทุกข้อ → กด 'ส่งแบบสอบถาม'")
        print("   3. popup เด้ง → กด 'ยืนยันการส่งแบบสอบถาม'")
        print("   4. รอ 30 วินาที — script เก็บทุก request")
        print("="*60 + "\n")
        await client.page.wait_for_timeout(5*60*1000)


if __name__ == "__main__":
    asyncio.run(main())
