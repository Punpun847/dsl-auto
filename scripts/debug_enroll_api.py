"""Click enroll button + capture POST enroll2learning response"""
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

        # collect all enroll-related responses
        collected = []

        async def maybe_capture(resp):
            url = resp.url
            if "/api/site/" in url and ("enroll" in url or f"courses/{course_id}" in url or f"groups/SETStudentLoan" in url):
                try:
                    body = await resp.text()
                except Exception as e:
                    body = f"<err: {e}>"
                collected.append({
                    "method": resp.request.method,
                    "url": url,
                    "status": resp.status,
                    "body": body[:3000],
                })

        client.page.on("response", lambda r: asyncio.create_task(maybe_capture(r)))

        # click + wait + check confirmation dialog
        print(">>> click .btn-trigger-enroll")
        await client.page.locator('.btn-trigger-enroll').first.click()
        await client.page.wait_for_timeout(3000)

        # ตรวจ confirm dialog (jquery-confirm) ที่อาจขึ้นมา
        confirm_state = await client.page.evaluate(r"""() => {
            const jc = document.querySelectorAll('.jconfirm, .jconfirm-box, [class*="jconfirm"]');
            const visibleConfirm = Array.from(jc).filter(el => el.offsetWidth || el.offsetHeight).map(el => ({
                cls: el.className?.toString().slice(0, 150),
                text: (el.innerText || '').trim().slice(0, 500),
            }));
            return {jcCount: jc.length, visibleConfirm};
        }""")
        print("confirm state:", json.dumps(confirm_state, ensure_ascii=False, indent=2))

        # ถ้ามี confirm dialog → click "ตกลง"
        if confirm_state["visibleConfirm"]:
            print(">>> click 'ตกลง' in confirm dialog")
            ok_btn = client.page.locator('.jconfirm-buttons button:has-text("ตกลง"), .jconfirm-box button:has-text("ตกลง")')
            if await ok_btn.count() > 0:
                await ok_btn.first.click()
                await client.page.wait_for_timeout(5000)

        # รอ navigation
        await client.page.wait_for_timeout(5000)

        print(f"\n=== final url: {client.page.url}")
        print(f"\n=== collected responses ({len(collected)}) ===")
        for c in collected:
            print(f"\n[{c['method']} {c['status']}] {c['url']}")
            print(c['body'][:1500])

        await client.page.screenshot(path="/tmp/debug_enroll_final.png", full_page=True)


if __name__ == "__main__":
    asyncio.run(main())
