"""
ทดสอบ POST ไปที่ SET /api/set/SETStudentLoan/login ด้วย data + signature จาก JWT
แล้วตรวจว่า session authenticated หรือเปล่า

Usage:
    cd gyso-backend
    venv/bin/python scripts/debug_set_post_login.py NID PWD [COURSE_ID]
"""
import asyncio
import base64
import json
import sys
from pathlib import Path

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
        print("Usage: debug_set_post_login.py NID PWD [COURSE_ID]")
        sys.exit(1)
    nid, pwd = sys.argv[1], sys.argv[2]
    course_id = sys.argv[3] if len(sys.argv) > 3 else "1941"

    jwt_holder = {}

    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        print(f"login: {'OK' if ok else 'FAIL'}")
        if not ok:
            return

        await client.page.wait_for_timeout(2000)
        ctx = client.page.context

        # ── ดัก SetLogin JWT ────────────────────────────────────
        async def on_resp(resp):
            if "SetLogin" in resp.url:
                body = await resp.text()
                jwt_holder["jwt"] = body
                jwt_holder["status"] = resp.status

        client.page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        # ── click SET ─────────────────────────────────────────────
        set_link = client.page.locator('#routeSETBtn, a:has-text("SET e-Learning")')
        await set_link.first.click()

        # รอ JWT
        for _ in range(10):
            await asyncio.sleep(1)
            if jwt_holder:
                break

        if not jwt_holder:
            print("ไม่ได้รับ JWT จาก SetLogin")
            return

        payload = decode_jwt_payload(jwt_holder["jwt"])
        data_obj = payload.get("data", {})
        location = data_obj.get("location", "")
        data_param = data_obj.get("data", "")
        sig_param = data_obj.get("signature", "")

        print(f"\nJWT payload:")
        print(f"  location: {location}")
        print(f"  data[:50]: {data_param[:50]}")
        print(f"  signature[:50]: {sig_param[:50]}")

        # ── ทดสอบ POST ผ่าน form submit ─────────────────────────
        # approach: inject form แล้ว submit → navigate current page ไป SET
        print("\n── approach 1: form POST บน current page ──")
        await client.page.evaluate(f"""() => {{
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '{location}';
            // ไม่มี target — navigate page นี้เอง
            const d = document.createElement('input');
            d.name = 'data';
            d.value = {json.dumps(data_param)};
            form.appendChild(d);
            const s = document.createElement('input');
            s.name = 'signature';
            s.value = {json.dumps(sig_param)};
            form.appendChild(s);
            document.body.appendChild(form);
            form.submit();
        }}""")

        # รอ navigation
        try:
            await client.page.wait_for_load_state("domcontentloaded", timeout=15_000)
        except Exception:
            pass
        await asyncio.sleep(3)

        url_after = client.page.url
        print(f"URL หลัง POST: {url_after}")
        await client.page.screenshot(path="/tmp/debug_set_post_01_after_post.png", full_page=True)

        cookies = await ctx.cookies()
        set_cookies = [c for c in cookies if "set.or.th" in c.get("domain", "")]
        print(f"SET cookies ({len(set_cookies)}): {[c['name'] for c in set_cookies]}")

        if not set_cookies:
            print("ไม่มี SET cookies — POST อาจ fail")

            # approach 2: ลอง fetch POST
            print("\n── approach 2: fetch POST จาก SET context ──")
            # ไปหน้า SET ก่อนเพื่อ same-origin
            await client.page.goto("https://elearning.set.or.th/SETStudentLoan",
                                   wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2)

            result = await client.page.evaluate(f"""async () => {{
                const form = new FormData();
                form.append('data', {json.dumps(data_param)});
                form.append('signature', {json.dumps(sig_param)});
                const body = new URLSearchParams();
                body.append('data', {json.dumps(data_param)});
                body.append('signature', {json.dumps(sig_param)});
                const r = await fetch('{location}', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-Requested-With': 'XMLHttpRequest',
                    }},
                    credentials: 'include',
                    body: body.toString(),
                }});
                return {{
                    status: r.status,
                    url: r.url,
                    redirected: r.redirected,
                    body: (await r.text()).slice(0, 500),
                }};
            }}""")
            print(f"fetch POST → status: {result.get('status')}, redirected: {result.get('redirected')}")
            print(f"  url: {result.get('url')}")
            print(f"  body[:200]: {result.get('body', '')[:200]}")

            cookies2 = await ctx.cookies()
            set_cookies2 = [c for c in cookies2 if "set.or.th" in c.get("domain", "")]
            print(f"\nSET cookies หลัง fetch ({len(set_cookies2)}): {[c['name'] for c in set_cookies2]}")
            set_cookies = set_cookies2

        # ── ถ้าได้ cookies แล้ว ทดสอบ enroll ───────────────────
        if set_cookies:
            print("\n✅ มี SET cookies! ทดสอบ enroll...")

            await client.page.goto(f"https://elearning.set.or.th/SETStudentLoan/courses/{course_id}/info",
                                   wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2)
            await client.page.reload(wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2)

            captured = []
            async def cap(resp):
                if "/api/site/" in resp.url:
                    try:
                        body = await resp.text()
                    except Exception:
                        body = "<err>"
                    captured.append((resp.status, resp.url, body[:200]))
                    print(f"  [{resp.status}] {resp.url}")
                    print(f"  body: {body[:150]}")

            client.page.on("response", lambda r: asyncio.create_task(cap(r)))

            enroll_btn = client.page.locator(
                '.btn-trigger-enroll, button:has-text("เข้าเรียน"), button:has-text("ลงทะเบียน")'
            )
            if await enroll_btn.count() > 0:
                await enroll_btn.first.click()
                await asyncio.sleep(2)
                ok_btn = client.page.locator('.jconfirm-buttons button:has-text("ตกลง")')
                if await ok_btn.count() > 0:
                    await ok_btn.first.click()
                await asyncio.sleep(5)
                print(f"\nURL หลัง enroll: {client.page.url}")
            else:
                print("ไม่เจอปุ่ม enroll")
                await client.page.screenshot(path="/tmp/debug_set_post_02_course.png", full_page=True)


if __name__ == "__main__":
    asyncio.run(main())
