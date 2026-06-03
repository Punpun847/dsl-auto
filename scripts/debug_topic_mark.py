"""Navigate ไป topic page แล้ว capture ทุก POST request → ดู actual payload ของ mark complete"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_BASE  # noqa: E402


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()

        # หา enroll_id ของ course นี้
        info = await client.page.evaluate(f"""async () => {{
            const r = await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}', {{credentials:'include'}});
            return r.json();
        }}""")
        enroll_id = info.get("enroll_id")
        print(f"enroll_id = {enroll_id}")
        if not enroll_id:
            print("ไม่มี enroll_id — ต้อง enroll ก่อน")
            return

        # ดึง topic แรกที่ยังไม่เสร็จ
        ed = await client.page.evaluate(f"async () => (await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}})).json()")
        topics = []
        def walk(ns):
            for n in (ns or []):
                if isinstance(n.get('parent'), list) and n.get('parent'):
                    walk(n['parent'])
                else:
                    topics.append(n)
        walk(ed.get('topics') or [])
        target = next((t for t in topics if int(t.get('percentage') or 0) < 100), topics[0])
        print(f"topic_id = {target['id']} ({target.get('title')})")
        e2t = target.get("enroll2topic") or {}
        print(f"enroll2topic_id = {e2t.get('id')}")

        # Spy: ดักทุก POST
        # debug print topics list
        for t in topics:
            e2t = (t.get('enroll2topic') or {}).get('id')
            print(f"  topic {t['id']} pct={t.get('percentage')} state={t.get('state')} e2t={e2t} title={t.get('title','')[:40]}")
        print()

        async def on_request(req):
            if "/api/site/" in req.url and req.method != "GET":
                ct = req.headers.get('content-type', '')
                print(f">>> {req.method} {req.url}")
                print(f"    Content-Type: {ct}")
                print(f"    BODY: {req.post_data}")

        client.page.on("request", on_request)

        # Navigate ไป topic — เล่น video อัตโนมัติ + รอ 120 วินาที
        url = f"{SET_BASE}/enroll/{enroll_id}/topics/{target['id']}"
        print(f"→ {url}\n")
        await client.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(3_000)

        # ลองกดเล่น video เลย
        try:
            await client.page.evaluate("""() => {
                const v = document.querySelector('video');
                if (v) { v.muted = true; v.play().catch(()=>{}); v.playbackRate = 16; console.log('▶ video play x16'); }
            }""")
        except Exception as e:
            print(f"video play err: {e}")

        print("รอ 120 วินาที — ดูทุก POST ที่ออก...")
        await client.page.wait_for_timeout(120_000)


if __name__ == "__main__":
    asyncio.run(main())
