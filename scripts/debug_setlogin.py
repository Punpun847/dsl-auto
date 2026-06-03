"""
ดัก response body ของ POST /api/v1/set-api/SetLogin
และ capture new page ที่เปิดหลัง SSO

Usage:
    cd gyso-backend
    venv/bin/python scripts/debug_setlogin.py NID PWD
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient  # noqa: E402


async def main():
    if len(sys.argv) < 3:
        print("Usage: debug_setlogin.py NID PWD")
        sys.exit(1)
    nid, pwd = sys.argv[1], sys.argv[2]

    setlogin_body = {}
    new_page_holder = []

    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        print(f"login: {'OK' if ok else 'FAIL'}")
        if not ok:
            return

        await client.page.wait_for_timeout(2000)

        ctx = client.page.context

        # ── ดัก new page event ก่อน click ────────────────────────
        async def on_new_page(page):
            print(f"🆕 new page created (URL: {page.url})")
            new_page_holder.append(page)

        ctx.on("page", on_new_page)

        # ── ดัก SetLogin response ─────────────────────────────────
        async def on_response(resp):
            if "set-api/SetLogin" in resp.url or "SetLogin" in resp.url:
                try:
                    body = await resp.text()
                    setlogin_body["url"] = resp.url
                    setlogin_body["status"] = resp.status
                    setlogin_body["body"] = body
                    print(f"\n✅ SetLogin response ({resp.status}):")
                    print(f"   {body[:500]}")
                except Exception as e:
                    print(f"SetLogin response error: {e}")

        client.page.on("response", lambda r: asyncio.create_task(on_response(r)))

        # ── click SET link ────────────────────────────────────────
        set_link = client.page.locator('#routeSETBtn, a:has-text("SET e-Learning")')
        count = await set_link.count()
        print(f"SET link: {count}")
        if count > 0:
            await set_link.first.click()
        else:
            print("ไม่เจอ #routeSETBtn")
            return

        # รอ SetLogin response + new page (นานขึ้น)
        print("รอ SetLogin + new page...")
        for i in range(20):  # รอสูงสุด 20 วิ
            await asyncio.sleep(1)
            if setlogin_body and new_page_holder:
                print(f"ได้ทั้งคู่แล้วใน {i+1}s")
                break
            if setlogin_body and i >= 5:
                print(f"มี SetLogin แล้ว แต่ไม่มี new page หลัง {i+1}s")
                break

        print(f"\nSetLogin body: {json.dumps(setlogin_body, ensure_ascii=False)[:800]}")
        print(f"new pages: {len(new_page_holder)}")

        # ── ตรวจ new page ─────────────────────────────────────────
        if new_page_holder:
            pg = new_page_holder[0]
            try:
                await pg.wait_for_load_state("domcontentloaded", timeout=20_000)
                await pg.wait_for_timeout(2000)
                print(f"\nnew page URL: {pg.url}")
                await pg.screenshot(path="/tmp/debug_setlogin_new_page.png", full_page=True)

                # ตรวจ cookies
                cookies = await ctx.cookies()
                set_cookies = [c for c in cookies if "set.or.th" in c.get("domain", "")]
                print(f"SET cookies ({len(set_cookies)}): {[c['name'] for c in set_cookies]}")

                # ทดสอบ POST enroll จาก page นี้ (course 1941 = enrolled แล้ว)
                print("\nทดสอบ POST enroll2learning จาก new page...")
                test = await pg.evaluate("""async () => {
                    const xsrfCookie = document.cookie.split(';')
                        .map(c => c.trim().split('='))
                        .find(([k]) => k === 'XSRF-TOKEN');
                    const xsrf = xsrfCookie ? decodeURIComponent(xsrfCookie[1]) : '';
                    try {
                        const r = await fetch('/api/site/enroll2learning', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'X-Requested-With': 'XMLHttpRequest',
                                'X-XSRF-TOKEN': xsrf,
                            },
                            credentials: 'include',
                            body: 'cid=1941&tid=&type=&pid=&ftype=',
                        });
                        return { status: r.status, body: (await r.text()).slice(0, 300) };
                    } catch(e) { return { error: e.message }; }
                }""")
                print(f"  status: {test.get('status')} | body: {test.get('body', '')[:200]}")

            except Exception as e:
                print(f"new page error: {e}")
        else:
            print("\nไม่มี new page เปิดขึ้น")
            # ดู URL ปัจจุบัน
            print(f"main page URL: {client.page.url}")

            # ถ้า SetLogin มี body — ดึง URL จาก response แล้วไป navigate เอง
            if setlogin_body.get("body"):
                try:
                    data = json.loads(setlogin_body["body"])
                    print(f"SetLogin JSON keys: {list(data.keys())}")
                    # หา URL ใน response
                    def find_urls(obj, depth=0):
                        if depth > 5:
                            return
                        if isinstance(obj, str) and ("http" in obj or "token" in obj.lower()):
                            print(f"  value: {obj[:200]}")
                        elif isinstance(obj, dict):
                            for k, v in obj.items():
                                print(f"  {'  '*depth}key: {k}")
                                find_urls(v, depth+1)
                        elif isinstance(obj, list):
                            for item in obj:
                                find_urls(item, depth+1)
                    find_urls(data)
                except Exception as e:
                    print(f"parse error: {e}")
                    print(f"raw: {setlogin_body.get('body', '')[:500]}")

        Path("/tmp/debug_setlogin.json").write_text(
            json.dumps({"setlogin": setlogin_body}, ensure_ascii=False, indent=2)
        )
        print("\n💾 /tmp/debug_setlogin.json")


if __name__ == "__main__":
    asyncio.run(main())
