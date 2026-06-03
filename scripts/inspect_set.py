"""
Inspect SET e-learning page โครงสร้างหลักสูตร
"""
import asyncio
import json
from playwright.async_api import async_playwright

SET_URL = "https://elearning.set.or.th/SETStudentLoan"
OUT = "/tmp/set_inspect.json"


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=100)
    ctx = await browser.new_context(locale="th-TH", viewport={"width": 1400, "height": 900})
    page = await ctx.new_page()

    await page.goto(SET_URL, wait_until="networkidle", timeout=30_000)
    await asyncio.sleep(3)

    await page.screenshot(path="/tmp/set_elearning.png", full_page=True)

    # ดึงข้อมูลโครงสร้างหลักสูตรหลายแบบ
    info = await page.evaluate("""() => {
        const grab = (sel) => Array.from(document.querySelectorAll(sel)).slice(0, 20).map(el => ({
            tag: el.tagName,
            id: el.id,
            class: el.className?.toString().slice(0, 80),
            text: el.innerText?.trim().slice(0, 200),
        }));
        return {
            url: location.href,
            title: document.title,
            h1: grab('h1, h2'),
            cards: grab('.card, .course, .course-card, [class*="course"], [class*="lesson"]'),
            buttons: grab('button, a.btn'),
            links: grab('a').filter(l => l.text).slice(0, 30),
            bodyText: document.body.innerText.slice(0, 1500),
        };
    }""")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"WROTE {OUT}", flush=True)
    await asyncio.sleep(600)


if __name__ == "__main__":
    asyncio.run(main())
