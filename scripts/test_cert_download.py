"""ทดสอบ flow: POST cert + คลิกปุ่ม download + capture file"""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_BASE  # noqa: E402


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()
        info = await client.page.evaluate(f"async () => (await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}', {{credentials:'include'}})).json()")
        eid = info.get("enroll_id")
        print(f"enroll_id={eid}")

        await client.page.goto(f"{SET_BASE}/enroll/{eid}/summary", wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(3_000)

        # 1. POST cert generate
        gen = await client.page.evaluate(f"""async () => {{
            const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
            const r = await fetch('/api/site/enroll/{eid}/certificate', {{
                method:'POST', headers:h, credentials:'include',
            }});
            return {{ status: r.status, body: await r.text() }};
        }}""")
        print(f"POST cert status={gen['status']}")
        print(f"  body: {gen['body'][:300]}\n")

        # 2. GET /certificate/th — ตาม redirect แบบไม่ follow + ดู Location
        info = await client.page.evaluate(f"""async () => {{
            const r = await fetch('/api/site/enroll/{eid}/certificate/th', {{
                credentials:'include', redirect:'manual',
            }});
            return {{ status: r.status, type: r.type, headers: [...r.headers.entries()] }};
        }}""")
        print(f"\nGET cert/th status={info['status']} type={info['type']}")
        for k, v in info.get('headers', []):
            print(f"  {k}: {v}")

        # 3. คลิกปุ่ม btn-download-certificate + capture download
        print("\n--- คลิกปุ่ม ---")
        async def on_download(d):
            path = f"/tmp/cert_{course_id}_download.pdf"
            await d.save_as(path)
            print(f"💾 DOWNLOAD: {d.suggested_filename} → {path}")

        client.page.on("download", on_download)

        async def on_new_page(p):
            print(f"📄 NEW PAGE: {p.url}")
            await p.wait_for_load_state("domcontentloaded", timeout=10_000)
            print(f"   final URL: {p.url}")

        client.page.context.on("page", on_new_page)

        await client.page.evaluate("""() => {
            const btn = document.querySelector('.btn-download-certificate');
            if (btn) { btn.disabled = false; btn.click(); }
        }""")

        await client.page.wait_for_timeout(10_000)


if __name__ == "__main__":
    asyncio.run(main())
