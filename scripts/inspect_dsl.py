"""
Debug script — เปิด browser ดู DSL portal เพื่อหา selectors จริง
"""
import asyncio
import json
from playwright.async_api import async_playwright

LOGIN_URL = "https://wsa.dsl.studentloan.or.th/#/rms/rms-login"
OUT = "/tmp/dsl_inspect.json"


async def inspect_page(page):
    inputs = await page.evaluate("""() => Array.from(document.querySelectorAll('input')).map(el => ({
        type: el.type, name: el.name, id: el.id,
        placeholder: el.placeholder, class: el.className,
        formControlName: el.getAttribute('formcontrolname'),
    }))""")
    buttons = await page.evaluate("""() => Array.from(document.querySelectorAll('button, a.btn, [role="button"]')).map(el => ({
        tag: el.tagName, type: el.type, id: el.id,
        class: el.className, text: el.innerText?.trim().slice(0, 80),
    }))""")
    return {"url": page.url, "title": await page.title(), "inputs": inputs, "buttons": buttons}


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=100)
    ctx = await browser.new_context(locale="th-TH", viewport={"width": 1400, "height": 900})
    page = await ctx.new_page()

    await page.goto(LOGIN_URL, wait_until="networkidle", timeout=30_000)
    await asyncio.sleep(2)

    await page.screenshot(path="/tmp/dsl_login.png", full_page=True)
    data = await inspect_page(page)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"WROTE {OUT}", flush=True)
    await asyncio.sleep(600)  # 10 นาที — login เอง แล้วเดินทาง e-learning


if __name__ == "__main__":
    asyncio.run(main())
