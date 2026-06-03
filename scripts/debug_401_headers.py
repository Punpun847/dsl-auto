"""
Capture full request headers + cookies ของ POST /enroll2learning
เพื่อ compare กับ browser จริง → หาว่า header อะไรที่ขาดทำให้เกิด 401

Usage:
    cd gyso-backend
    venv/bin/python scripts/debug_401_headers.py NID PWD COURSE_ID

Output:
    /tmp/debug_401_headers.json  — request headers + cookies dump
    /tmp/debug_401_before.png    — หน้าก่อนกด enroll
    /tmp/debug_401_after.png     — หน้าหลัง enroll (ดูว่า redirect ไปไหน)
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_LIST_URL, SET_BASE  # noqa: E402


async def main():
    if len(sys.argv) < 4:
        print("Usage: debug_401_headers.py NID PWD COURSE_ID")
        sys.exit(1)
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]

    captured_requests = []
    captured_responses = []

    headless = "--headless" not in sys.argv
    async with DSLClient(headless=headless) as client:
        # ── login + SSO ──────────────────────────────────────────
        ok = await client.login(nid, pwd)
        print(f"login: {'OK' if ok else 'FAIL'}")
        ok = await client.goto_set()
        print(f"goto_set: {'OK' if ok else 'FAIL'}")

        # ── ไปหน้า course ─────────────────────────────────────────
        course_url = f"{SET_BASE}/courses/{course_id}/info"
        print(f"\nไปที่: {course_url}")
        await client.page.goto(course_url, wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(2000)
        # reload เพื่อ rehydrate session (session race bug ที่รู้)
        await client.page.reload(wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(2000)
        await client.page.screenshot(path="/tmp/debug_401_before.png", full_page=True)
        print(f"URL ปัจจุบัน: {client.page.url}")

        # ── dump cookies ก่อนกด ───────────────────────────────────
        cookies_before = await client.page.context.cookies()
        set_cookies = [c for c in cookies_before if "set.or.th" in c.get("domain", "")]
        dsl_cookies = [c for c in cookies_before if "dsl" in c.get("domain", "")]
        print(f"\n=== Cookies บน elearning.set.or.th ({len(set_cookies)}) ===")
        for c in set_cookies:
            print(f"  {c['name']} = {c['value'][:60]}  [domain={c['domain']} secure={c.get('secure')} httpOnly={c.get('httpOnly')}]")
        print(f"\n=== Cookies บน DSL ({len(dsl_cookies)}) ===")
        for c in dsl_cookies:
            print(f"  {c['name']} = {c['value'][:60]}")

        # ── ดัก request ก่อนส่ง ───────────────────────────────────
        async def capture_request(req):
            if "/api/site/" in req.url:
                headers = req.headers
                captured_requests.append({
                    "method": req.method,
                    "url": req.url,
                    "headers": dict(headers),
                    "post_data": req.post_data or "",
                })
                print(f"\n[REQUEST] {req.method} {req.url}")
                for k, v in headers.items():
                    print(f"  {k}: {v[:120]}")

        async def capture_response(resp):
            if "/api/site/" in resp.url:
                try:
                    body = await resp.text()
                except Exception as e:
                    body = f"<err: {e}>"
                captured_responses.append({
                    "method": resp.request.method,
                    "url": resp.url,
                    "status": resp.status,
                    "headers": dict(resp.headers),
                    "body": body[:3000],
                })
                print(f"\n[RESPONSE] {resp.status} {resp.url}")
                print(f"  body: {body[:500]}")

        client.page.on("request", lambda r: asyncio.create_task(capture_request(r)))
        client.page.on("response", lambda r: asyncio.create_task(capture_response(r)))

        # ── กด enroll ─────────────────────────────────────────────
        enroll_btn = client.page.locator(
            '.btn-trigger-enroll, button:has-text("เข้าเรียน"), button:has-text("ลงทะเบียน")'
        )
        count = await enroll_btn.count()
        print(f"\nปุ่ม enroll เจอ: {count}")
        if count == 0:
            print("ไม่เจอปุ่ม — ดู screenshot /tmp/debug_401_before.png")
            return

        btn_text = await enroll_btn.first.inner_text()
        print(f"text ปุ่ม: '{btn_text.strip()}'")
        await enroll_btn.first.click()
        await client.page.wait_for_timeout(2000)

        # handle $.confirm modal
        confirm_ok = client.page.locator('.jconfirm-buttons button:has-text("ตกลง")')
        if await confirm_ok.count() > 0 and await confirm_ok.first.is_visible(timeout=1000):
            print(">>> กด ตกลง ใน $.confirm modal")
            await confirm_ok.first.click()
        else:
            print("ไม่มี modal (หรือปิดไปแล้ว)")

        # รอให้ request/response บินผ่าน
        await client.page.wait_for_timeout(5000)
        await client.page.screenshot(path="/tmp/debug_401_after.png", full_page=True)
        print(f"\nURL หลัง enroll: {client.page.url}")

        # ── dump cookies หลังกด ───────────────────────────────────
        cookies_after = await client.page.context.cookies()
        set_cookies_after = [c for c in cookies_after if "set.or.th" in c.get("domain", "")]
        new_cookies = {c["name"] for c in set_cookies_after} - {c["name"] for c in set_cookies}
        if new_cookies:
            print(f"\n=== Cookie ใหม่หลัง enroll: {new_cookies} ===")

        # ── สรุป ──────────────────────────────────────────────────
        print(f"\n=== สรุป requests ที่ดักได้ ({len(captured_requests)}) ===")
        for r in captured_requests:
            print(f"  {r['method']} {r['url']}")
        print(f"\n=== สรุป responses ({len(captured_responses)}) ===")
        for r in captured_responses:
            print(f"  {r['status']} {r['method']} {r['url']}")

        # บันทึก JSON สำหรับ compare กับ browser จริง
        dump = {
            "cookies_before": set_cookies,
            "requests": captured_requests,
            "responses": captured_responses,
        }
        out = Path("/tmp/debug_401_headers.json")
        out.write_text(json.dumps(dump, ensure_ascii=False, indent=2))
        print(f"\n💾 dump บันทึกที่: {out}")
        print("📸 ก่อน: /tmp/debug_401_before.png")
        print("📸 หลัง: /tmp/debug_401_after.png")

        if not headless:
            input("\n[Enter เพื่อปิด browser]")


if __name__ == "__main__":
    asyncio.run(main())
