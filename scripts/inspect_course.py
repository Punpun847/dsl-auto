"""
Inspect หน้า course detail บน SET e-learning
รัน:
    python scripts/inspect_course.py <NID> <PWD> <COURSE_ID>

จะ output:
    /tmp/course_<id>_landing.png    — screenshot หน้าแรก
    /tmp/course_<id>_player.png     — screenshot หน้า player (ถ้าเข้าได้)
    /tmp/course_<id>_inspect.json   — DOM structure + selectors ที่ candidate
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.worker.dsl_client import DSLClient, SET_LIST_URL  # noqa: E402

COURSE_URL_TMPL = "https://elearning.set.or.th/SETStudentLoan/courses/{id}"
OUT_DIR = Path("/tmp")


async def inspect_page(page, label: str) -> dict:
    """ดึงโครงสร้าง DOM ที่น่าจะเกี่ยวกับ player / lesson / quiz / cert"""
    return await page.evaluate(r"""(label) => {
        const grab = (sel, max = 30) => Array.from(document.querySelectorAll(sel))
            .slice(0, max).map(el => ({
                tag: el.tagName,
                id: el.id || null,
                cls: (el.className?.toString() || '').slice(0, 120),
                text: (el.innerText || '').trim().slice(0, 240),
                href: el.href || null,
                src: el.src || null,
            }));
        const videos = Array.from(document.querySelectorAll('video')).map(v => ({
            src: v.src || v.currentSrc || null,
            duration: v.duration || null,
            paused: v.paused,
            muted: v.muted,
            playbackRate: v.playbackRate,
            readyState: v.readyState,
            parent_cls: (v.parentElement?.className?.toString() || '').slice(0, 120),
        }));
        const iframes = Array.from(document.querySelectorAll('iframe')).map(f => ({
            src: f.src, cls: (f.className?.toString() || '').slice(0, 120),
        }));
        // ลอง selector หลายแบบสำหรับ lesson/episode list
        const lessonSelectors = [
            '.lesson-item', '.episode-item', '.chapter-item',
            '[class*="lesson"]', '[class*="episode"]', '[class*="chapter"]',
            '.list-group-item', '.video-list li', 'ul.playlist li',
            'a[href*="lesson"]', 'a[href*="episode"]', 'a[href*="video"]',
        ];
        const lessonsByCandidate = {};
        lessonSelectors.forEach(sel => {
            const found = document.querySelectorAll(sel);
            if (found.length > 0) {
                lessonsByCandidate[sel] = {
                    count: found.length,
                    sample: Array.from(found).slice(0, 5).map(el => ({
                        text: (el.innerText || '').trim().slice(0, 120),
                        href: el.href || el.querySelector('a')?.href || null,
                        cls: (el.className?.toString() || '').slice(0, 120),
                    })),
                };
            }
        });
        // quiz / cert / start buttons
        const quizSelectors = [
            'a:has-text', 'button:has-text',  // playwright-only, จะ skip
            '[class*="quiz"]', '[class*="test"]', '[class*="exam"]',
            '[class*="certificate"]', '[class*="cert"]',
        ];
        const quizish = [];
        document.querySelectorAll('a, button').forEach(el => {
            const t = (el.innerText || '').trim();
            if (!t || t.length > 80) return;
            if (/quiz|ทดสอบ|แบบทดสอบ|ทำข้อสอบ|certificate|วุฒิบัตร|ดาวน์โหลด|download|เริ่มเรียน|ดูต่อ|เรียนต่อ/i.test(t)) {
                quizish.push({
                    tag: el.tagName,
                    text: t.slice(0, 120),
                    href: el.href || null,
                    cls: (el.className?.toString() || '').slice(0, 120),
                });
            }
        });
        return {
            label,
            url: location.href,
            title: document.title,
            videos,
            iframes,
            lessonsByCandidate,
            quizish: quizish.slice(0, 30),
            buttons: grab('button', 20),
            links_count: document.querySelectorAll('a').length,
            body_preview: document.body.innerText.slice(0, 2000),
        };
    }""", label)


async def main():
    if len(sys.argv) < 4:
        print("usage: python scripts/inspect_course.py <NID> <PWD> <COURSE_ID>")
        sys.exit(1)

    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    course_url = COURSE_URL_TMPL.format(id=course_id)

    # ใช้ headed mode เห็นกับตา (DSL_DEBUG ใน env ก็ได้)
    async with DSLClient(headless=False) as client:
        print(f"[1/4] login as {nid[:6]}…")
        ok = await client.login(nid, pwd)
        if not ok:
            print(f"❌ login failed: {client.last_error}")
            sys.exit(2)

        # SSO ไป SET โดย click link เดียวกับ fetch_courses
        print("[2/4] SSO → SET e-learning")
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

        # ไปหน้า list ก่อน เพื่อให้แน่ใจว่า session อยู่
        await client.page.goto(SET_LIST_URL, wait_until="networkidle", timeout=30_000)
        await client.page.wait_for_timeout(1500)

        # หา card ของ course_id ใน list (รองรับ pagination)
        print(f"[3/4] หา course card id={course_id} ใน list")
        card_selector = f'a.card-course[href*="/courses/{course_id}"]'
        clicked = False
        for page_num in range(1, 21):
            loc = client.page.locator(card_selector)
            if await loc.count() > 0:
                print(f"   เจอ card ที่หน้า {page_num} → click")
                await loc.first.scroll_into_view_if_needed()
                await loc.first.click()
                await client.page.wait_for_load_state("networkidle", timeout=20_000)
                await client.page.wait_for_timeout(2500)
                clicked = True
                break
            # ลองไปหน้าถัดไป
            next_btn = client.page.locator(
                '.pagination a[rel="next"], .pagination li.next:not(.disabled) a'
            )
            if await next_btn.count() == 0:
                print(f"   ไม่เจอ card และไม่มีหน้าถัดไป (อยู่หน้า {page_num})")
                break
            await next_btn.first.click()
            await client.page.wait_for_load_state("networkidle", timeout=15_000)
            await client.page.wait_for_timeout(1500)

        if not clicked:
            print(f"❌ ไม่พบ card ของ course {course_id} ใน list — fallback goto ตรง")
            await client.page.goto(course_url, wait_until="networkidle", timeout=30_000)
            await client.page.wait_for_timeout(2500)
        else:
            print(f"   landed at {client.page.url}")

        # บังคับ reload เพื่อให้ SPA re-fetch state ด้วย cookie ที่ติดมาแล้ว
        print("   reload หน้า /info เพื่อ refresh state…")
        await client.page.reload(wait_until="domcontentloaded", timeout=30_000)
        await client.page.wait_for_timeout(3000)

        # รอ enrolled button จริงๆ (ไม่นับ "ลงทะเบียน")
        try:
            await client.page.wait_for_function(
                """() => {
                    const btns = Array.from(document.querySelectorAll('button, a.btn'));
                    return btns.some(b => {
                        const t = b.innerText || '';
                        const vis = b.offsetWidth || b.offsetHeight;
                        return vis && /เข้าเรียน|เริ่มเรียน|ดูต่อ|เรียนต่อ/.test(t);
                    });
                }""",
                timeout=8_000,
            )
            print("   ✓ เจอ enrolled button")
        except Exception:
            print("   ⚠️  ยังไม่เจอ enrolled button — อาจไม่ได้ลงทะเบียน หรือ session ไม่ติด")
        await client.page.wait_for_timeout(1500)
        await client.page.screenshot(
            path=str(OUT_DIR / f"course_{course_id}_landing.png"), full_page=True
        )
        landing_info = await inspect_page(client.page, "landing")

        # === Full flow: register → confirm → pretest (random) → player ===
        print("[4/4] full flow: register → pretest → player")
        player_info = None
        pretest_info = None

        # detect state: enrolled (มี "เข้าเรียน") vs not_enrolled (แค่ "ลงทะเบียน")
        state = await client.page.evaluate(r"""() => {
            const btns = Array.from(document.querySelectorAll('button, a.btn, a'));
            const visible = btns.filter(b => b.offsetWidth || b.offsetHeight);
            const texts = visible.map(b => (b.innerText || '').trim());
            const hasEnter = texts.some(t => /^(เข้าเรียน|เริ่มเรียน|ดูต่อ|เรียนต่อ)$/.test(t));
            const hasRegister = texts.some(t => /^ลงทะเบียน$/.test(t));
            return {hasEnter, hasRegister, sampleTexts: texts.filter(t => t).slice(0, 30)};
        }""")
        print(f"   state: enter={state['hasEnter']} register={state['hasRegister']}")

        # 4a. ถ้า NOT enrolled (ไม่มี "เข้าเรียน" แต่มี "ลงทะเบียน") → click + ยืนยัน
        if not state['hasEnter'] and state['hasRegister']:
            enroll_btn = client.page.locator('.btn-trigger-enroll, button:has-text("ลงทะเบียน")')
            print("   4a. click ลงทะเบียน")
            await enroll_btn.first.click()
            await client.page.wait_for_timeout(2000)
            await client.page.screenshot(
                path=str(OUT_DIR / f"course_{course_id}_enroll_modal.png"), full_page=True
            )
            # หา confirm button ใน modal (text "ยืนยัน" / "ตกลง" / "ยืนยันและชำระเงิน")
            confirm_sel = (
                'button:has-text("ยืนยันและชำระเงิน"), '
                'button:has-text("ยืนยัน"):not(:has-text("ยกเลิก")), '
                'button:has-text("ตกลง"), '
                '#btnCreateOrder'
            )
            confirm = client.page.locator(confirm_sel)
            cnt = await confirm.count()
            print(f"   4a. confirm buttons found: {cnt}")
            if cnt > 0:
                for i in range(cnt):
                    b = confirm.nth(i)
                    if await b.is_visible():
                        txt = (await b.inner_text()).strip()
                        print(f"   4a. click confirm: '{txt}'")
                        await b.click()
                        break
                await client.page.wait_for_timeout(3000)
            else:
                print("   4a. ⚠️ ไม่เจอ confirm — skip")
        else:
            print("   4a. skip register (enrolled แล้ว)")

        # 4b. รอปุ่ม "เข้าเรียน" / "เริ่มเรียน" / "ดูต่อ" แล้วคลิก
        print("   4b. รอ enter button")
        try:
            await client.page.wait_for_function(
                """() => {
                    const btns = Array.from(document.querySelectorAll('button, a.btn, a'));
                    return btns.some(b => {
                        const t = (b.innerText || '').trim();
                        const vis = b.offsetWidth || b.offsetHeight;
                        return vis && /^(เข้าเรียน|เริ่มเรียน|ดูต่อ|เรียนต่อ|ทำแบบทดสอบ)$/.test(t);
                    });
                }""",
                timeout=15_000,
            )
        except Exception:
            print("   4b. ⚠️ ไม่เจอ enter button ใน 15 วิ")

        enter_selectors = [
            'a:has-text("เข้าเรียน")', 'button:has-text("เข้าเรียน")',
            'a:has-text("เริ่มเรียน")', 'button:has-text("เริ่มเรียน")',
            'a:has-text("ดูต่อ")', 'button:has-text("ดูต่อ")',
            'a:has-text("เรียนต่อ")', 'button:has-text("เรียนต่อ")',
            'a:has-text("ทำแบบทดสอบ")', 'button:has-text("ทำแบบทดสอบ")',
        ]
        clicked_enter = False
        for sel in enter_selectors:
            try:
                loc = client.page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=500):
                    print(f"   4b. click {sel}")
                    await loc.first.click()
                    try:
                        await client.page.wait_for_load_state("domcontentloaded", timeout=15_000)
                    except Exception:
                        pass
                    await client.page.wait_for_timeout(4000)
                    clicked_enter = True
                    break
            except Exception as e:
                print(f"   4b. skip {sel}: {e}")
                continue
        if not clicked_enter:
            print("   4b. ⚠️ คลิก enter button ไม่ได้")

        # 4c. screenshot หลังคลิก enter — เพื่อดูว่ามี pretest modal/page หรือเข้า player เลย
        await client.page.screenshot(
            path=str(OUT_DIR / f"course_{course_id}_after_enter.png"), full_page=True
        )
        print(f"   4c. after-enter screenshot saved | url={client.page.url}")

        # 4d. ลอง detect + ทำ pretest แบบมั่วๆ (วน max 30 รอบ เผื่อ multi-step)
        print("   4d. หา pretest + ตอบมั่ว")
        for step in range(30):
            # หา radio/checkbox ที่ยังไม่ติ๊ก แล้วคลิก 1 ตัวต่อ question group
            picked = await client.page.evaluate(r"""() => {
                const inputs = Array.from(document.querySelectorAll(
                    'input[type="radio"], input[type="checkbox"]'
                )).filter(i => i.offsetWidth || i.offsetHeight);
                if (inputs.length === 0) return {picked: 0, groups: 0};
                // group by name
                const groups = {};
                inputs.forEach(i => {
                    const key = i.name || i.getAttribute('data-name') || ('g_' + Math.random());
                    if (!groups[key]) groups[key] = [];
                    groups[key].push(i);
                });
                let picked = 0;
                Object.values(groups).forEach(arr => {
                    const anyChecked = arr.some(i => i.checked);
                    if (!anyChecked) {
                        // pick first
                        const target = arr[0];
                        // ใช้ label click ถ้ามี — เผื่อ input ถูก hide
                        const label = target.closest('label') ||
                            document.querySelector(`label[for="${target.id}"]`);
                        (label || target).click();
                        picked++;
                    }
                });
                return {picked, groups: Object.keys(groups).length};
            }""")
            print(f"     step {step+1}: picked={picked['picked']} / groups={picked['groups']}")

            # หา submit/next button
            await client.page.wait_for_timeout(500)
            submit_sel = (
                'button:has-text("ส่งคำตอบ"):not([disabled]), '
                'button:has-text("ส่ง"):not([disabled]), '
                'button:has-text("ถัดไป"):not([disabled]), '
                'button:has-text("ต่อไป"):not([disabled]), '
                'button:has-text("ยืนยัน"):not(:has-text("ยกเลิก")):not([disabled]), '
                'button:has-text("เสร็จสิ้น"):not([disabled]), '
                'button[type="submit"]:not([disabled])'
            )
            sb = client.page.locator(submit_sel)
            sb_cnt = await sb.count()
            if sb_cnt == 0 and picked['groups'] == 0:
                print("     ไม่เจอ radio + ไม่เจอ submit → น่าจะ pretest จบแล้ว")
                break
            if sb_cnt > 0:
                # ตัวที่ visible
                for i in range(sb_cnt):
                    b = sb.nth(i)
                    if await b.is_visible():
                        txt = (await b.inner_text()).strip()
                        print(f"     click '{txt}'")
                        await b.click()
                        await client.page.wait_for_timeout(2500)
                        break
                continue
            # ถ้ามี radio แต่ไม่มี submit ก็รอแล้ววน
            await client.page.wait_for_timeout(1500)
        else:
            print("     ⚠️ pretest loop ครบ 30 รอบ — ตัดออก")

        # 4e. screenshot pretest end + inspect
        await client.page.screenshot(
            path=str(OUT_DIR / f"course_{course_id}_pretest_end.png"), full_page=True
        )
        pretest_info = await inspect_page(client.page, "pretest_end")

        # 4f. รอเข้า player → screenshot
        print(f"   4f. รอ player render | url={client.page.url}")
        await client.page.wait_for_timeout(5000)
        await client.page.screenshot(
            path=str(OUT_DIR / f"course_{course_id}_player.png"), full_page=True
        )
        player_info = await inspect_page(client.page, "player")

        out = {
            "course_id": course_id,
            "course_url": course_url,
            "landing": landing_info,
            "pretest_end": pretest_info,
            "player": player_info,
        }
        out_path = OUT_DIR / f"course_{course_id}_inspect.json"
        out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ wrote {out_path}")
        print(f"✅ screenshots: {OUT_DIR}/course_{course_id}_landing.png + _player.png")
        print("\nรอ 60 วิ ให้ดู browser แล้วปิดเอง…")
        await client.page.wait_for_timeout(60_000)


if __name__ == "__main__":
    asyncio.run(main())
