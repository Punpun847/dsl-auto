"""
ตรวจสอบ SSO flow จาก DSL → SET อย่างละเอียด
เพื่อหาว่า laravel_session ที่ได้มา = authenticated user หรือแค่ guest

Usage:
    cd gyso-backend
    venv/bin/python scripts/debug_sso_flow.py NID PWD

Output:
    /tmp/debug_sso_*.png
    /tmp/debug_sso_flow.json
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_BASE  # noqa: E402


async def main():
    if len(sys.argv) < 3:
        print("Usage: debug_sso_flow.py NID PWD")
        sys.exit(1)
    nid, pwd = sys.argv[1], sys.argv[2]

    result = {}

    async with DSLClient(headless=True) as client:
        # ── login DSL ────────────────────────────────────────────
        ok = await client.login(nid, pwd)
        print(f"login: {'OK' if ok else 'FAIL'}")
        if not ok:
            return

        await client.page.screenshot(path="/tmp/debug_sso_01_after_login.png", full_page=True)

        # ── หา href ของ SET e-Learning link ──────────────────────
        set_link = client.page.locator(
            'a:has-text("SET e-Learning"), a:has-text("SET e-learning"), '
            'a:has-text("Set e-learning")'
        )
        count = await set_link.count()
        print(f"\nพบ SET link: {count}")

        if count > 0:
            href = await set_link.first.get_attribute("href")
            text = await set_link.first.inner_text()
            print(f"  text: '{text.strip()}'")
            print(f"  href: {href}")
            result["set_link_href"] = href
            result["set_link_text"] = text.strip()

        # ── track navigations บน new page ─────────────────────────
        nav_log = []

        ctx = client.page.context

        async def on_request(req):
            if req.resource_type in ("document",):
                nav_log.append({"type": "req", "method": req.method, "url": req.url})

        async def on_response(resp):
            if resp.request.resource_type in ("document",):
                nav_log.append({"type": "resp", "status": resp.status, "url": resp.url})

        # ── click SET link + ตาม redirect ─────────────────────────
        try:
            async with ctx.expect_page(timeout=10_000) as np_info:
                await set_link.first.click()
            new_page = await np_info.value
            print("\nเปิด tab ใหม่")
        except Exception as e:
            print(f"\nไม่มี tab ใหม่ ({e}) — ใช้ page เดิม")
            new_page = client.page

        new_page.on("request", lambda r: asyncio.create_task(on_request(r)))
        new_page.on("response", lambda r: asyncio.create_task(on_response(r)))

        # รอให้ SSO redirect chain เสร็จ (นานขึ้น ไม่ตัดก่อน)
        try:
            await new_page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass

        # รอ JavaScript render (SSO อาจมี redirect หลายชั้น)
        await new_page.wait_for_timeout(4000)

        url_after_sso = new_page.url
        print(f"\nURL หลัง SSO click + 4s: {url_after_sso}")
        result["url_after_sso"] = url_after_sso
        await new_page.screenshot(path="/tmp/debug_sso_02_after_click.png", full_page=True)

        # ── ตรวจ cookies ──────────────────────────────────────────
        cookies = await ctx.cookies()
        set_cookies = [c for c in cookies if "set.or.th" in c.get("domain", "")]
        print(f"\nCookies บน set.or.th: {len(set_cookies)}")
        cookie_names = [c["name"] for c in set_cookies]
        print(f"  {cookie_names}")
        has_session = any(c["name"] == "laravel_session" for c in set_cookies)
        print(f"  laravel_session: {'✅' if has_session else '❌'}")
        result["cookies_after_sso"] = [{"name": c["name"], "domain": c["domain"]} for c in set_cookies]

        # ── ทดสอบว่า user authenticated จริงไหม ──────────────────
        # เรียก endpoint ที่ต้องการ auth — ถ้า 401 = guest, ถ้า 200 = logged in
        auth_tests = [
            f"{SET_BASE}/api/site/user",
            f"{SET_BASE}/api/site/profile",
            f"{SET_BASE}/api/site/my-courses",
            f"{SET_BASE}/api/site/groups/SETStudentLoan/my-enrollments",
        ]

        print("\n── ทดสอบ auth endpoints ──")
        client.page = new_page  # ใช้ page ที่ SSO แล้ว

        auth_results = []
        for url in auth_tests:
            try:
                resp = await new_page.evaluate(f"""async () => {{
                    try {{
                        const r = await fetch('{url}', {{
                            headers: {{
                                'X-Requested-With': 'XMLHttpRequest',
                                'Accept': 'application/json',
                            }},
                            credentials: 'include',
                        }});
                        const text = await r.text();
                        return {{ status: r.status, body: text.slice(0, 300) }};
                    }} catch(e) {{ return {{ status: -1, error: e.message }}; }}
                }}""")
                status = resp.get("status")
                body = resp.get("body", "")[:200]
                print(f"  {status} {url.split('/')[-1]}  →  {body[:100]}")
                auth_results.append({"url": url, "status": status, "body": body})
            except Exception as e:
                print(f"  ERR {url}: {e}")
                auth_results.append({"url": url, "status": -1, "error": str(e)})

        result["auth_tests"] = auth_results

        # ── ทดสอบ POST enroll2learning โดยตรงจาก page นี้ ─────────
        print("\n── ทดสอบ POST enroll2learning จาก page หลัง SSO ──")
        # ก่อน POST ต้อง navigate ไปหน้า course ก่อน เพื่อให้ CSRF token ถูก context
        await new_page.goto(f"{SET_BASE}/courses/1942/info", wait_until="domcontentloaded", timeout=30_000)
        await new_page.wait_for_timeout(2000)

        # ดึง CSRF token จาก meta tag
        csrf = await new_page.evaluate("""() => {
            const m = document.querySelector('meta[name="csrf-token"]');
            return m ? m.content : null;
        }""")
        print(f"  CSRF token จาก meta: {csrf}")
        result["csrf_from_meta"] = csrf

        enroll_resp = await new_page.evaluate("""async () => {
            const csrf = document.querySelector('meta[name="csrf-token"]')?.content || '';
            const xsrf = document.cookie.split(';')
                .map(c => c.trim().split('='))
                .find(([k]) => k === 'XSRF-TOKEN');
            const xsrfVal = xsrf ? decodeURIComponent(xsrf[1]) : '';

            try {
                const r = await fetch('/api/site/enroll2learning', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-CSRF-TOKEN': csrf,
                        'Accept': 'application/json',
                    },
                    credentials: 'include',
                    body: new URLSearchParams({
                        groups_id: 'SETStudentLoan',
                        courses_id: '1942',
                    }).toString(),
                });
                const text = await r.text();
                return { status: r.status, body: text.slice(0, 500),
                         csrf_used: csrf, xsrf_available: !!xsrfVal };
            } catch(e) {
                return { status: -1, error: e.message };
            }
        }""")
        print(f"  POST /enroll2learning → status: {enroll_resp.get('status')}")
        print(f"  body: {enroll_resp.get('body', '')[:300]}")
        print(f"  csrf_used: {enroll_resp.get('csrf_used', '')[:40]}")
        result["direct_post_test"] = enroll_resp

        # ── navigation log ────────────────────────────────────────
        print(f"\n── Navigation log ({len(nav_log)}) ──")
        for n in nav_log:
            if n["type"] == "req":
                print(f"  → {n['method']} {n['url'][:100]}")
            else:
                print(f"  ← {n['status']} {n['url'][:100]}")
        result["nav_log"] = nav_log

        # ── save ──────────────────────────────────────────────────
        out = Path("/tmp/debug_sso_flow.json")
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\n💾 dump: {out}")


if __name__ == "__main__":
    asyncio.run(main())
