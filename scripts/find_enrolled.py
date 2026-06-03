"""
หา course ที่ user ลงทะเบียนแล้ว (มีปุ่ม "เริ่มเรียน"/"ดูต่อ"/"เรียนต่อ" บนหน้า /info)
โดย dump card HTML เต็มจากหน้า list ก่อน เพื่อดูว่ามี indicator บน card หรือไม่
ถ้าไม่มี จะ visit /info ของแต่ละ course (จำกัด N ตัวแรก) เพื่อ check ปุ่ม
รัน:
    python scripts/find_enrolled.py <NID> <PWD> [MAX_VISIT=5]
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_LIST_URL  # noqa: E402

OUT = Path("/tmp/find_enrolled.json")


async def sso_to_set(client):
    set_link = client.page.locator(
        'a:has-text("SET e-Learning"), a:has-text("SET e-learning"), '
        'a:has-text("Set e-learning")'
    )
    ctx = client.page.context
    if await set_link.count() > 0:
        try:
            async with ctx.expect_page(timeout=10_000) as new_info:
                await set_link.first.click()
            client.page = await new_info.value
        except Exception:
            await set_link.first.click()
        await client.page.wait_for_load_state("networkidle", timeout=20_000)


async def main():
    if len(sys.argv) < 3:
        print("usage: python scripts/find_enrolled.py <NID> <PWD> [MAX_VISIT=5]")
        sys.exit(1)

    nid, pwd = sys.argv[1], sys.argv[2]
    max_visit = int(sys.argv[3]) if len(sys.argv) > 3 else 5

    async with DSLClient(headless=True) as client:
        print(f"[1/3] login as {nid[:6]}…")
        ok = await client.login(nid, pwd)
        if not ok:
            print(f"login failed: {client.last_error}")
            sys.exit(2)

        print("[2/3] SSO + goto list")
        await sso_to_set(client)
        await client.page.goto(SET_LIST_URL, wait_until="networkidle", timeout=30_000)
        await client.page.wait_for_timeout(1500)

        # ดู card HTML เต็ม + ลองหา progress/status text บน card
        cards = await client.page.evaluate(r"""() => {
            return Array.from(document.querySelectorAll('a.card-course')).map(card => {
                const url = card.href || '';
                const idMatch = url.match(/courses\/(\d+)/);
                return {
                    id: idMatch ? idMatch[1] : null,
                    url,
                    fullText: (card.innerText || '').trim(),
                    classes: card.className?.toString() || '',
                    hasProgress: !!card.querySelector('[class*="progress"]'),
                    progressText: card.querySelector('[class*="progress"]')?.innerText?.trim() || null,
                    badgeText: card.querySelector('.badge, [class*="badge"]')?.innerText?.trim() || null,
                };
            });
        }""")
        print(f"   หน้าแรก: {len(cards)} cards")

        # check ปุ่มของ N course แรก
        print(f"[3/3] visit หน้า /info ของ {max_visit} course แรก เพื่อ check ปุ่ม")
        results = []
        for i, c in enumerate(cards[:max_visit]):
            cid = c["id"]
            if not cid:
                continue
            card_sel = f'a.card-course[href*="/courses/{cid}"]'
            try:
                await client.page.goto(SET_LIST_URL, wait_until="networkidle", timeout=30_000)
                await client.page.wait_for_timeout(800)
                loc = client.page.locator(card_sel)
                if await loc.count() == 0:
                    print(f"   [{i+1}] id={cid} — card ไม่เจอ skip")
                    continue
                await loc.first.click()
                await client.page.wait_for_load_state("networkidle", timeout=15_000)
                await client.page.wait_for_timeout(1500)

                btn_info = await client.page.evaluate(r"""() => {
                    const btns = Array.from(document.querySelectorAll('button, a.btn'));
                    return btns
                        .map(b => ({
                            tag: b.tagName,
                            text: (b.innerText || '').trim().slice(0, 60),
                            cls: (b.className?.toString() || '').slice(0, 120),
                            href: b.href || null,
                            visible: !!(b.offsetWidth || b.offsetHeight),
                        }))
                        .filter(b => b.visible && b.text);
                }""")

                # judge enrolled vs not
                texts = " | ".join(b["text"] for b in btn_info)
                enrolled = any(k in texts for k in ["เริ่มเรียน", "ดูต่อ", "เรียนต่อ", "เข้าเรียน"])
                pending = "ลงทะเบียน" in texts
                status = "ENROLLED ✓" if enrolled else ("NOT_ENROLLED" if pending else "?")
                print(f"   [{i+1}] id={cid} {status}  buttons: {texts[:120]}")
                results.append({
                    "id": cid, "url": c["url"], "title": c["fullText"][:80],
                    "status": status, "buttons": btn_info,
                })
            except Exception as e:
                print(f"   [{i+1}] id={cid} ERROR: {e}")

        OUT.write_text(json.dumps({"cards": cards, "checked": results},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nwrote {OUT}")
        enrolled_ids = [r["id"] for r in results if "ENROLLED" in r["status"]]
        if enrolled_ids:
            print(f"✓ enrolled course ids: {enrolled_ids}")
        else:
            print("✗ ยังไม่เจอ enrolled course ใน N ตัวแรก — เพิ่ม MAX_VISIT แล้วลองใหม่")


if __name__ == "__main__":
    asyncio.run(main())
