"""ดูว่า cert endpoint คืน HTML อะไรกลับมา — แล้วลองหา API จริงของการ generate cert"""
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
        print(f"enroll_id={eid}\n")

        # ดักทุก request หลังเปิด summary
        async def on_req(r):
            if "/api/site/" in r.url:
                print(f">>> {r.method} {r.url[:120]}")
                if r.post_data:
                    print(f"    BODY: {r.post_data[:200]}")
        async def on_resp(r):
            if "/api/site/" in r.url:
                try:
                    txt = (await r.text())[:300]
                except:
                    txt = "<err>"
                print(f"<<< {r.status} {r.url[:120]}")
                print(f"    RESP: {txt}\n")

        client.page.on("request", on_req)
        client.page.on("response", on_resp)

        await client.page.goto(f"{SET_BASE}/enroll/{eid}/summary", wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(3_000)
        print("\n--- summary page loaded ---")

        # ลองค้นหา cert button หรือ link
        buttons = await client.page.evaluate("""() => {
            const out = [];
            ['button','a','.btn-download-certificate','[onclick*="cert"]'].forEach(s => {
                document.querySelectorAll(s).forEach(el => {
                    const t = (el.innerText||'').trim();
                    if (t && (t.toLowerCase().includes('cert') || t.includes('วุฒิ') || t.includes('ดาวน์โหลด'))) {
                        out.push({tag: el.tagName, text: t.slice(0,80), cls: el.className.slice(0,80), href: el.href, onclick: el.getAttribute('onclick')});
                    }
                });
            });
            return out;
        }""")
        print(f"\ncert buttons found: {len(buttons)}")
        for b in buttons:
            print(f"  {b}")

        # ดู HTML cert/th ตรงๆ
        print("\n--- direct cert fetch ---")
        await client.page.evaluate(f"async () => {{ const r = await fetch('/api/site/enroll/{eid}/certificate/th', {{credentials:'include'}}); console.log('cert status', r.status); }}")
        await client.page.wait_for_timeout(2_000)
        await client.page.wait_for_timeout(60_000)


if __name__ == "__main__":
    asyncio.run(main())
