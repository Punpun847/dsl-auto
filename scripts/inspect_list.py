"""
Inspect SET e-learning list page (หลักสูตรที่เหลือของ user)
"""
import asyncio
import json
from playwright.async_api import async_playwright

LIST_URL = "https://elearning.set.or.th/SETStudentLoan/list"
OUT = "/tmp/set_list.json"


async def main():
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False, slow_mo=100)
    ctx = await browser.new_context(locale="th-TH", viewport={"width": 1400, "height": 900})
    page = await ctx.new_page()

    await page.goto(LIST_URL, wait_until="networkidle", timeout=30_000)
    await asyncio.sleep(3)

    await page.screenshot(path="/tmp/set_list.png", full_page=True)

    info = await page.evaluate("""() => {
        const grab = (sel, max=30) => Array.from(document.querySelectorAll(sel)).slice(0, max).map(el => ({
            tag: el.tagName,
            id: el.id,
            class: el.className?.toString().slice(0, 120),
            text: el.innerText?.trim().slice(0, 300),
            href: el.href,
            attrs: {
                'data-course-id': el.getAttribute('data-course-id'),
                'data-id': el.getAttribute('data-id'),
            },
        }));
        return {
            url: location.href,
            title: document.title,
            cards: grab('.card, .course, [class*="course"]'),
            cardEmbossed: grab('.card-embossed, .a-card-embossed'),
            links: grab('a').filter(l => l.text && l.text.length > 5),
            bodyTextSample: document.body.innerText.slice(0, 2000),
        };
    }""")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"WROTE {OUT}", flush=True)
    await asyncio.sleep(600)


if __name__ == "__main__":
    asyncio.run(main())
