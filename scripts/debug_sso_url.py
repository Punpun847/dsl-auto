"""
ตรวจสอบ SET e-Learning link บน DSL portal อย่างละเอียด
และ track ว่า click แล้วเปิด URL อะไรบน SET (SSO URL จริง)

Usage:
    cd gyso-backend
    venv/bin/python scripts/debug_sso_url.py NID PWD
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient  # noqa: E402


async def main():
    if len(sys.argv) < 3:
        print("Usage: debug_sso_url.py NID PWD")
        sys.exit(1)
    nid, pwd = sys.argv[1], sys.argv[2]

    async with DSLClient(headless=True) as client:
        ok = await client.login(nid, pwd)
        print(f"login: {'OK' if ok else 'FAIL'} — URL: {client.page.url}")
        if not ok:
            return

        await client.page.wait_for_timeout(2000)
        await client.page.screenshot(path="/tmp/debug_sso_url_01_after_login.png", full_page=True)

        # ── ตรวจ DOM ของ SET link อย่างละเอียด ──────────────────
        link_info = await client.page.evaluate(r"""() => {
            const keywords = ['SET e-Learning', 'SET e-learning', 'set e-learning',
                              'Set e-learning', 'SET', 'elearning'];
            const results = [];
            document.querySelectorAll('a, button, [role="button"], [onclick]').forEach(el => {
                const text = (el.innerText || el.textContent || '').trim();
                if (keywords.some(k => text.toLowerCase().includes(k.toLowerCase()))) {
                    results.push({
                        tag: el.tagName,
                        text: text.slice(0, 80),
                        href: el.href || null,
                        onclick: (el.getAttribute('onclick') || '').slice(0, 200),
                        class: (el.className?.toString() || '').slice(0, 100),
                        id: el.id || null,
                        outerHTML: el.outerHTML.slice(0, 300),
                    });
                }
            });
            return results;
        }""")
        print(f"\nพบ SET-related elements: {len(link_info)}")
        for el in link_info:
            print(f"\n  tag={el['tag']} id={el['id']}")
            print(f"  text: '{el['text']}'")
            print(f"  href: {el['href']}")
            print(f"  onclick: {el['onclick']}")
            print(f"  class: {el['class']}")
            print(f"  outerHTML: {el['outerHTML'][:200]}")

        # ── track ทุก page ที่อาจเปิดขึ้นมา ─────────────────────
        ctx = client.page.context
        new_pages = []

        def on_page(page):
            new_pages.append(page)
            print(f"\n🆕 new page: {page.url}")

        ctx.on("page", on_page)

        # ── track requests บน page ปัจจุบัน ──────────────────────
        nav_history = []

        async def on_req(req):
            if req.resource_type in ("document", "xhr", "fetch"):
                nav_history.append(f"→ {req.method} {req.url[:120]}")

        async def on_resp(resp):
            if resp.request.resource_type in ("document", "xhr", "fetch"):
                nav_history.append(f"← {resp.status} {resp.url[:120]}")

        client.page.on("request", lambda r: asyncio.create_task(on_req(r)))
        client.page.on("response", lambda r: asyncio.create_task(on_resp(r)))

        # ── inject JS เพื่อดัก window.open ───────────────────────
        await client.page.evaluate("""() => {
            const orig = window.open;
            window.__openedUrls = [];
            window.open = function(url, ...args) {
                window.__openedUrls.push(url);
                console.log('window.open intercepted:', url);
                return orig.call(window, url, ...args);
            };
        }""")

        # ── click SET link ─────────────────────────────────────────
        set_link = client.page.locator(
            'a:has-text("SET e-Learning"), a:has-text("SET e-learning"), '
            'a:has-text("Set e-learning"), button:has-text("SET e-Learning"), '
            'button:has-text("SET e-learning")'
        )
        count = await set_link.count()
        print(f"\nSET link count: {count}")

        if count > 0:
            print("คลิก SET link...")
            await set_link.first.click()
        else:
            print("ไม่เจอ SET link — ลองกด element แรก:")
            if link_info:
                # ลอง click โดย evaluate
                await client.page.evaluate("""() => {
                    const keywords = ['SET e-Learning', 'SET e-learning'];
                    for (const el of document.querySelectorAll('a, button')) {
                        if (keywords.some(k => el.innerText?.includes(k))) {
                            el.click();
                            return el.outerHTML.slice(0, 200);
                        }
                    }
                    return 'not found';
                }""")

        # รอดู
        await asyncio.sleep(6)

        opened_urls = await client.page.evaluate("() => window.__openedUrls || []")
        print(f"\nwindow.open ถูกเรียก: {opened_urls}")
        print(f"new pages ที่เปิด: {len(new_pages)}")
        for p in new_pages:
            print(f"  page URL: {p.url}")
            try:
                await p.wait_for_load_state("domcontentloaded", timeout=10_000)
                print(f"  page URL หลัง load: {p.url}")
                # ดู cookie ที่ตั้งขึ้น
                cookies = await ctx.cookies()
                set_cookies = [c for c in cookies if "set.or.th" in c.get("domain", "")]
                print(f"  SET cookies: {[c['name'] for c in set_cookies]}")

                # check auth
                auth_check = await p.evaluate("""async () => {
                    try {
                        const r = await fetch('/api/site/enroll2learning', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'X-Requested-With': 'XMLHttpRequest',
                            },
                            credentials: 'include',
                            body: 'cid=1941&tid=&type=&pid=&ftype=',
                        });
                        return { status: r.status, body: (await r.text()).slice(0, 200) };
                    } catch(e) { return { error: e.message }; }
                }""")
                print(f"  POST enroll test → {auth_check}")
                await p.screenshot(path="/tmp/debug_sso_url_new_page.png", full_page=True)
            except Exception as e:
                print(f"  error: {e}")

        print(f"\nURL ปัจจุบัน (main page): {client.page.url}")
        print(f"\nNavigation log ({len(nav_history)}):")
        for h in nav_history[:30]:
            print(f"  {h}")

        await client.page.screenshot(path="/tmp/debug_sso_url_02_after_click.png", full_page=True)

        Path("/tmp/debug_sso_url.json").write_text(json.dumps({
            "link_info": link_info,
            "opened_urls": opened_urls,
            "nav_history": nav_history,
        }, ensure_ascii=False, indent=2))
        print("\n💾 /tmp/debug_sso_url.json")


if __name__ == "__main__":
    asyncio.run(main())
