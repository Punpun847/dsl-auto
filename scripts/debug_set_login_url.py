"""
จับ URL เต็มของ new page ที่ DSL เปิดหลัง SetLogin
เพื่อดูว่า data + signature ถูก encode ใน URL ยังไง

Usage:
    cd gyso-backend
    venv/bin/python scripts/debug_set_login_url.py NID PWD
"""
import asyncio
import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient  # noqa: E402


def decode_jwt_payload(jwt: str) -> dict:
    parts = jwt.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))


async def main():
    if len(sys.argv) < 3:
        print("Usage: debug_set_login_url.py NID PWD")
        sys.exit(1)
    nid, pwd = sys.argv[1], sys.argv[2]

    jwt_token = {}
    new_page_url = {}

    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        print(f"login: {'OK' if ok else 'FAIL'}")
        if not ok:
            return

        await client.page.wait_for_timeout(2000)
        ctx = client.page.context

        # ── จับ new page ─────────────────────────────────────────
        new_page_future = asyncio.get_event_loop().create_future()

        def on_new_page(page):
            if not new_page_future.done():
                new_page_future.set_result(page)

        ctx.on("page", on_new_page)

        # ── จับ SetLogin response ─────────────────────────────────
        async def on_resp(resp):
            if "SetLogin" in resp.url:
                body = await resp.text()
                jwt_token["jwt"] = body
                jwt_token["status"] = resp.status

        client.page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        # ── inject window.open interceptor ──────────────────────
        await client.page.evaluate("""() => {
            const orig = window.open;
            window.__openArgs = [];
            window.open = function(url, target, features) {
                window.__openArgs.push({ url, target, features });
                console.log('[intercepted] window.open:', url);
                return orig.call(window, url, target, features);
            };
        }""")

        # ── click SET ─────────────────────────────────────────────
        set_link = client.page.locator('#routeSETBtn, a:has-text("SET e-Learning")')
        await set_link.first.click()
        print("คลิก SET link แล้ว — รอ...")

        # รอ SetLogin response ก่อน
        for _ in range(10):
            await asyncio.sleep(1)
            if jwt_token:
                break

        if jwt_token:
            print(f"\nSetLogin status: {jwt_token['status']}")
            payload = decode_jwt_payload(jwt_token["jwt"])
            data_obj = payload.get("data", {})
            location = data_obj.get("location", "")
            data_param = data_obj.get("data", "")
            sig_param = data_obj.get("signature", "")
            print(f"location: {location}")
            print(f"data[:40]: {data_param[:40]}...")
            print(f"signature[:40]: {sig_param[:40]}...")

        # ── ดัก window.open args ──────────────────────────────────
        await asyncio.sleep(3)
        open_args = await client.page.evaluate("() => window.__openArgs || []")
        print(f"\nwindow.open calls: {len(open_args)}")
        for a in open_args:
            url = a.get("url", "")
            print(f"  url: {url[:300]}")
            if url:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                print(f"  path: {parsed.path}")
                print(f"  params: {list(params.keys())}")
                new_page_url["full_url"] = url
                new_page_url["path"] = parsed.path
                new_page_url["params"] = {k: v[0][:60] for k, v in params.items()}

        # ── รอ new page ───────────────────────────────────────────
        try:
            np = await asyncio.wait_for(new_page_future, timeout=8)
            await asyncio.sleep(2)
            print(f"\nnew page initial URL: {np.url}")
            try:
                await np.wait_for_load_state("domcontentloaded", timeout=15_000)
                await asyncio.sleep(2)
                print(f"new page final URL: {np.url}")
                await np.screenshot(path="/tmp/debug_set_login_url_newpage.png", full_page=True)
                cookies = await ctx.cookies()
                set_cookies = [c for c in cookies if "set.or.th" in c.get("domain", "")]
                print(f"SET cookies: {[c['name'] for c in set_cookies]}")

                # ทดสอบ auth
                auth = await np.evaluate("""async () => {
                    const r = await fetch('/api/site/enroll2learning', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/x-www-form-urlencoded',
                            'X-Requested-With': 'XMLHttpRequest',
                        },
                        credentials: 'include',
                        body: 'cid=1941&tid=&type=&pid=&ftype=',
                    });
                    return { status: r.status, body: (await r.text()).slice(0, 200) };
                }""")
                print(f"\nPOST enroll test → {auth}")
            except Exception as e:
                print(f"load error: {e}")
        except asyncio.TimeoutError:
            print("\nhมได้ new page ใน 8s")

        # ── สรุป: navigate ตรงๆ ไป SET login URL ─────────────────
        if jwt_token and not open_args:
            # Angular ไม่ได้ใช้ window.open — ลองดู href ตรงๆ
            payload = decode_jwt_payload(jwt_token["jwt"])
            data_obj = payload.get("data", {})
            location = data_obj.get("location", "")
            data_param = data_obj.get("data", "")
            sig_param = data_obj.get("signature", "")

            print(f"\n── ลอง navigate ตรงๆ ไป location URL ──")
            test_url = f"{location}?data={data_param}&signature={sig_param}"
            print(f"URL: {test_url[:200]}")
            from urllib.parse import quote
            encoded_url = f"{location}?data={quote(data_param)}&signature={quote(sig_param)}"
            print(f"encoded URL[:150]: {encoded_url[:150]}")

            await client.page.goto(encoded_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(3)
            print(f"URL หลัง navigate: {client.page.url}")
            await client.page.screenshot(path="/tmp/debug_set_login_url_direct.png", full_page=True)
            cookies = await ctx.cookies()
            set_cookies = [c for c in cookies if "set.or.th" in c.get("domain", "")]
            print(f"SET cookies: {[c['name'] for c in set_cookies]}")

        Path("/tmp/debug_set_login_url.json").write_text(
            json.dumps({"new_page_url": new_page_url, "open_args": open_args},
                       ensure_ascii=False, indent=2)
        )
        print("\n💾 /tmp/debug_set_login_url.json")


if __name__ == "__main__":
    asyncio.run(main())
