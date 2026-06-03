"""Click ปุ่ม btn-trigger-enroll แล้ว monitor: console, popup, network, DOM mutation"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_LIST_URL  # noqa: E402


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        set_link = client.page.locator(
            'a:has-text("SET e-Learning"), a:has-text("SET e-learning"), a:has-text("Set e-learning")'
        )
        ctx = client.page.context
        if await set_link.count() > 0:
            try:
                async with ctx.expect_page(timeout=10_000) as np:
                    await set_link.first.click()
                client.page = await np.value
            except Exception:
                await set_link.first.click()
            await client.page.wait_for_load_state("networkidle", timeout=20_000)

        await client.page.goto(SET_LIST_URL, wait_until="networkidle", timeout=30_000)
        await client.page.wait_for_timeout(1500)
        await client.page.locator(f'a.card-course[href*="/courses/{course_id}"]').first.click()
        await client.page.wait_for_load_state("domcontentloaded", timeout=15_000)
        await client.page.wait_for_timeout(2000)
        await client.page.reload(wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(3000)

        # attach listeners
        console_msgs = []
        client.page.on("console", lambda msg: console_msgs.append(f"[{msg.type}] {msg.text[:300]}"))
        requests = []
        client.page.on("request", lambda r: requests.append(f"{r.method} {r.url[:200]}"))
        responses = []
        api_bodies = []

        async def capture_body(resp):
            url = resp.url
            if any(k in url for k in ["enroll", "pretest", "lesson", "exam", "learning"]):
                try:
                    body = await resp.text()
                    api_bodies.append({"url": url, "status": resp.status, "body": body[:2000]})
                except Exception as e:
                    api_bodies.append({"url": url, "status": resp.status, "body": f"<error: {e}>"})

        client.page.on(
            "response",
            lambda r: (responses.append(f"{r.status} {r.url[:200]}"),
                       asyncio.create_task(capture_body(r))),
        )
        new_pages = []
        ctx.on("page", lambda p: new_pages.append(p.url))

        # ดูดู source ของ enroll() function ก่อน click
        enroll_src = await client.page.evaluate(
            "() => typeof enroll === 'function' ? enroll.toString().slice(0, 3000) : 'NOT_DEFINED'"
        )
        print("=== enroll() source ===")
        print(enroll_src)
        print()

        # ดู count modal/dialog ก่อน click
        before_state = await client.page.evaluate(r"""() => ({
            url: location.href,
            modalCount: document.querySelectorAll('.modal, .modal-content, [role="dialog"]').length,
            visibleModals: Array.from(document.querySelectorAll('.modal.show, .modal[style*="display: block"], [role="dialog"]:not([style*="display: none"])')).length,
            videoCount: document.querySelectorAll('video').length,
            iframeCount: document.querySelectorAll('iframe').length,
            bodyLen: document.body.innerText.length,
        })""")
        print("BEFORE click:", before_state)

        # click ปุ่ม
        print("\n>>> click btn-trigger-enroll")
        await client.page.locator('.btn-trigger-enroll').first.click()

        # monitor 12 วิ ทุก 2 วิ
        for i in range(6):
            await client.page.wait_for_timeout(2000)
            state = await client.page.evaluate(r"""() => ({
                url: location.href,
                modalCount: document.querySelectorAll('.modal, .modal-content, [role="dialog"]').length,
                visibleModals: Array.from(document.querySelectorAll('.modal, [role="dialog"]')).filter(m => {
                    const s = getComputedStyle(m);
                    return s.display !== 'none' && (m.offsetWidth || m.offsetHeight);
                }).map(m => ({
                    cls: m.className?.toString().slice(0, 100),
                    text: (m.innerText || '').trim().slice(0, 200),
                })),
                videoCount: document.querySelectorAll('video').length,
                videoSrc: Array.from(document.querySelectorAll('video')).map(v => v.src || v.currentSrc).filter(Boolean),
                iframeCount: document.querySelectorAll('iframe').length,
                bodyLen: document.body.innerText.length,
                pretestSign: !!document.querySelector('[class*="pretest"], [class*="pre-test"], [class*="quiz"], [class*="exam"]'),
            })""")
            print(f"\n--- t+{(i+1)*2}s ---")
            print(json.dumps(state, ensure_ascii=False, indent=2))
            if new_pages:
                print("NEW PAGES:", new_pages)
            if state["visibleModals"]:
                break

        print("\n=== console (last 20) ===")
        for m in console_msgs[-20:]:
            print("  ", m)
        print(f"\n=== requests count: {len(requests)}")
        # filter ที่เกี่ยว enroll
        for r in requests:
            if any(k in r.lower() for k in ["enroll", "register", "pretest", "lesson", "course", "exam"]):
                print("  REQ", r)
        print(f"\n=== responses (status != 200, filtered) ===")
        for r in responses:
            if any(k in r.lower() for k in ["enroll", "pretest", "lesson", "exam"]):
                print("  RES", r)

        await client.page.screenshot(path="/tmp/debug_after_enroll.png", full_page=True)
        print("\nสุดท้าย:", client.page.url)
        print("\n=== API response bodies ===")
        for ab in api_bodies:
            print(f"\n[{ab['status']}] {ab['url']}")
            print(ab['body'])


if __name__ == "__main__":
    asyncio.run(main())
