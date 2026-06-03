"""
ทดสอบ click enroll หลัง SSO โดยไม่ interrupt ด้วย goto(/list)
เพื่อหาว่า goto_set() ทำให้ session กลาย guest หรือเปล่า

Usage:
    cd gyso-backend
    venv/bin/python scripts/debug_enroll_nosso_interrupt.py NID PWD COURSE_ID
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_BASE  # noqa: E402


async def main():
    if len(sys.argv) < 4:
        print("Usage: debug_enroll_nosso_interrupt.py NID PWD COURSE_ID")
        sys.exit(1)
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]

    captured = []

    async with DSLClient(headless=True) as client:
        # ── login ────────────────────────────────────────────────
        ok = await client.login(nid, pwd)
        print(f"login: {'OK' if ok else 'FAIL'}")
        if not ok:
            return

        # ── SSO: click + รอให้เสร็จเอง ไม่ navigate ไป /list ────
        set_link = client.page.locator(
            'a:has-text("SET e-Learning"), a:has-text("SET e-learning"), '
            'a:has-text("Set e-learning")'
        )
        ctx = client.page.context
        try:
            async with ctx.expect_page(timeout=10_000) as np_info:
                await set_link.first.click()
            new_page = await np_info.value
            print("เปิด tab ใหม่")
        except Exception:
            new_page = client.page
            print("ไม่มี tab ใหม่ — ใช้ page เดิม")

        # รอ SSO ให้เสร็จสมบูรณ์ (ไม่ตัด)
        try:
            await new_page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass
        await new_page.wait_for_timeout(5000)
        print(f"URL หลัง SSO: {new_page.url}")

        # ── ไปหน้า course โดยตรง (ไม่แวะ /list) ──────────────────
        course_url = f"{SET_BASE}/courses/{course_id}/info"
        await new_page.goto(course_url, wait_until="domcontentloaded", timeout=30_000)
        await new_page.wait_for_timeout(2000)
        await new_page.reload(wait_until="domcontentloaded", timeout=30_000)
        await new_page.wait_for_timeout(2000)
        print(f"URL หน้า course: {new_page.url}")
        await new_page.screenshot(path="/tmp/debug_enroll_ni_01_course.png", full_page=True)

        # ── ดัก request/response ────────────────────────────────
        async def cap_req(req):
            if "/api/site/" in req.url:
                print(f"\n[REQ] {req.method} {req.url}")
                if req.post_data:
                    print(f"  body: {req.post_data[:200]}")
                captured.append({"dir": "req", "method": req.method, "url": req.url,
                                  "body": req.post_data or ""})

        async def cap_resp(resp):
            if "/api/site/" in resp.url:
                try:
                    body = await resp.text()
                except Exception:
                    body = "<err>"
                print(f"[RESP] {resp.status} {resp.url}")
                print(f"  body: {body[:300]}")
                captured.append({"dir": "resp", "status": resp.status,
                                  "url": resp.url, "body": body[:500]})

        new_page.on("request", lambda r: asyncio.create_task(cap_req(r)))
        new_page.on("response", lambda r: asyncio.create_task(cap_resp(r)))

        # ── click enroll ────────────────────────────────────────
        enroll_btn = new_page.locator(
            '.btn-trigger-enroll, button:has-text("เข้าเรียน"), '
            'button:has-text("ลงทะเบียน"), a:has-text("เข้าเรียน")'
        )
        count = await enroll_btn.count()
        print(f"\nปุ่ม enroll: {count}")
        if count == 0:
            print("ไม่เจอปุ่ม — ดู /tmp/debug_enroll_ni_01_course.png")
            return

        btn_text = await enroll_btn.first.inner_text()
        print(f"text: '{btn_text.strip()}'")
        await enroll_btn.first.click()
        await new_page.wait_for_timeout(2000)

        # handle modal
        confirm_ok = new_page.locator('.jconfirm-buttons button:has-text("ตกลง")')
        if await confirm_ok.count() > 0:
            print("กด ตกลง ใน modal")
            await confirm_ok.first.click()

        await new_page.wait_for_timeout(5000)
        await new_page.screenshot(path="/tmp/debug_enroll_ni_02_after.png", full_page=True)
        print(f"\nURL หลัง enroll: {new_page.url}")

        print(f"\n=== summary ({len(captured)}) ===")
        for c in captured:
            if c["dir"] == "resp":
                print(f"  {c['status']} {c['method'] if 'method' in c else ''} {c['url']}")

        Path("/tmp/debug_enroll_ni.json").write_text(
            json.dumps(captured, ensure_ascii=False, indent=2)
        )
        print("💾 /tmp/debug_enroll_ni.json")


if __name__ == "__main__":
    asyncio.run(main())
