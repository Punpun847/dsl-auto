"""Debug — เปิดหน้า /info ของ course แล้วดู DOM ของปุ่ม 'เข้าเรียน' ละเอียด"""
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
        # SSO
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
        card_sel = f'a.card-course[href*="/courses/{course_id}"]'
        await client.page.locator(card_sel).first.click()
        await client.page.wait_for_load_state("domcontentloaded", timeout=15_000)
        await client.page.wait_for_timeout(2000)
        await client.page.reload(wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(3000)

        # หา element ที่มี text "เข้าเรียน" + dump ละเอียด
        info = await client.page.evaluate(r"""() => {
            const all = Array.from(document.querySelectorAll('button, a, [class*="btn"]'));
            const matches = all.filter(el => {
                const t = (el.innerText || '').trim();
                return t === 'เข้าเรียน' || t === 'เริ่มเรียน' || t === 'ดูต่อ' || t === 'เรียนต่อ';
            }).slice(0, 20);
            return matches.map(el => ({
                tag: el.tagName,
                id: el.id || null,
                cls: (el.className?.toString() || '').slice(0, 200),
                href: el.href || null,
                target: el.target || null,
                onclick: el.onclick ? 'has' : null,
                text: (el.innerText || '').trim().slice(0, 80),
                visible: !!(el.offsetWidth || el.offsetHeight),
                rect: (() => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; })(),
                outerHTML: el.outerHTML.slice(0, 500),
                parentTag: el.parentElement?.tagName,
                parentCls: (el.parentElement?.className?.toString() || '').slice(0, 120),
            }));
        }""")
        print(json.dumps(info, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
