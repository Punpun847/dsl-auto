"""
DSL portal client — login + scrape courses + watch videos
URL: https://wsa.dsl.studentloan.or.th (Angular SPA, hash routing)
"""
import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, Page

from app.config import settings as _app_settings

logger = logging.getLogger("dsl_client")
logger.setLevel(logging.INFO)

DSL_BASE = "https://wsa.dsl.studentloan.or.th"
LOGIN_URL = f"{DSL_BASE}/#/rms/rms-login"
SET_BASE = "https://elearning.set.or.th/SETStudentLoan"
SET_LIST_URL = f"{SET_BASE}/list"
SET_COURSE_URL = f"{SET_BASE}/courses/{{id}}/info"
# Iterate ทุกแท็บใน sidebar — กัน bug ฝั่ง SET ที่แท็บ "ทั้งหมด" ไม่ sync กับแท็บย่อย
SET_CATEGORY_URLS = [
    ("all",          SET_LIST_URL),
    ("planning",     f"{SET_BASE}/categories/45"),   # การวางแผนการเงิน
    ("investing",    f"{SET_BASE}/categories/48"),   # หลักการลงทุน
    ("entrepreneur", f"{SET_BASE}/categories/63"),   # หลักสูตรผู้ประกอบการ
    ("mutualfund",   f"{SET_BASE}/categories/136"),  # การลงทุนในกองทุนรวม
]
PRICE_PER_HOUR = 3
# tuning จาก settings — แก้ผ่าน .env ได้ (DSL_VIDEO_SPEED, DSL_WATCH_TIMEOUT_SEC ฯลฯ)
VIDEO_SPEED = _app_settings.dsl_video_speed
WATCH_TIMEOUT_SEC = _app_settings.dsl_watch_timeout_sec

# cross-platform tmp dir — /tmp/ ไม่มีบน Windows
_TMP = Path(tempfile.gettempdir()) / "gyso_dsl"
_TMP.mkdir(parents=True, exist_ok=True)
ANSWER_CACHE_FILE = str(_TMP / "exam_answer_cache.json")
SHOT_DIR = str(_TMP)

LogFn = Callable[[str, str, Optional[str]], Awaitable[None]]

# Debug mode: เปิด browser เห็นเลย + screenshot ทุก step
DEBUG = os.getenv("DSL_DEBUG", "0") == "1"


class DSLClient:
    def __init__(self, headless: Optional[bool] = None):
        self.headless = (not DEBUG) if headless is None else headless
        self.pw = None
        self._job_id: str = ""          # set by complete_course_via_api
        self._human_answer_timeout = _app_settings.dsl_human_answer_timeout
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.last_error: Optional[str] = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def _shot(self, name: str) -> None:
        if DEBUG and self.page:
            try:
                path = f"{SHOT_DIR}/dsl_{name}.png"
                await self.page.screenshot(path=path, full_page=True)
                logger.info(f"📸 screenshot {path} — URL: {self.page.url}")
            except Exception:
                pass

    async def start(self) -> None:
        logger.info(f"🚀 start browser (headless={self.headless})")
        self.pw = await async_playwright().start()
        # channel="chrome" ใช้ system Chrome แทน bundled Chromium —
        # แก้ side-by-side DLL error บน Windows. ถ้า Chrome ไม่ install จะ fall back
        try:
            self.browser = await self.pw.chromium.launch(
                headless=self.headless,
                slow_mo=100 if DEBUG else 0,
                channel="chrome",
            )
        except Exception as e:
            logger.warning(f"chrome channel ไม่พร้อม ({e}) — fall back bundled chromium")
            self.browser = await self.pw.chromium.launch(
                headless=self.headless,
                slow_mo=100 if DEBUG else 0,
            )
        ctx = await self.browser.new_context(locale="th-TH", viewport={"width": 1280, "height": 800})
        self.page = await ctx.new_page()

    async def _dismiss_popups(self, allow_escape: bool = False) -> None:
        """ปิด pop-up ประกาศข่าวที่บัง form login

        allow_escape: กด Escape เป็น fallback ถ้าหา selector ไม่เจอ
            ❌ ห้ามใช้บนหน้า Angular (SET / DSL portal หลัง login) — Escape รบกวน state
            ✅ ใช้ได้บน login page ก่อน Angular fully render
        """
        # ลอง selectors หลายตัว — ครอบคลุม modal patterns ทั่วไป + ปุ่มไทย
        selectors = [
            'button:has-text("ปิด")',
            'button:has-text("รับทราบ")',
            'button:has-text("ตกลง")',
            'button:has-text("ยอมรับ")',
            'button:has-text("Close")',
            'button[aria-label="Close"]',
            'button[aria-label="ปิด"]',
            '.modal button.close',
            '.modal .close-btn',
            '.btn-close',
            '[class*="modal"] button[class*="close"]',
            '.popup button',
            '.dialog button',
        ]
        for sel in selectors:
            try:
                loc = self.page.locator(sel)
                count = await loc.count()
                if count > 0 and await loc.first.is_visible(timeout=500):
                    logger.info(f"🚪 ปิด popup ด้วย selector: {sel}")
                    await loc.first.click(timeout=2000)
                    await self.page.wait_for_timeout(500)
                    return
            except Exception:
                continue

        if allow_escape:
            try:
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(300)
                logger.info("🚪 ส่ง Escape เผื่อปิด popup")
            except Exception:
                pass

    async def login_set(self, email: str, pwd: str) -> bool:
        """Login ตรงที่ member.set.or.th (ไม่ผ่าน DSL portal)
        ใช้เมื่อ user มีบัญชี SET โดยตรง — ไม่ใช่ user กยศ"""
        try:
            logger.info(f"🔑 (SET-direct) goto https://elearning.set.or.th/SETGroup")
            await self.page.goto(
                "https://elearning.set.or.th/SETGroup",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            await self.page.wait_for_timeout(2000)
            await self._dismiss_popups(allow_escape=False)

            # คลิก "เข้าสู่ระบบ"
            logger.info(f"🖱  click .btn-trigger-login")
            await self.page.locator(".btn-trigger-login").first.click(timeout=10_000)

            # รอ redirect ไป member.set.or.th
            await self.page.wait_for_url("**member.set.or.th**", timeout=20_000)
            await self.page.wait_for_timeout(1500)
            await self._shot("set_login_form")

            # fill email + password
            logger.info(f"⌨️  type email ({len(email)} chars)")
            email_input = self.page.locator(
                'input[type="text"][placeholder*="อีเมล"], input[type="email"]'
            ).first
            await email_input.fill(email)

            logger.info(f"⌨️  type password ({len(pwd)} chars)")
            await self.page.locator('input[type="password"]').first.fill(pwd)

            # submit
            logger.info(f"🖱  click .button-submit")
            await self.page.locator(".button-submit").first.click()

            # รอ redirect กลับไป elearning.set.or.th (success)
            try:
                await self.page.wait_for_url("**elearning.set.or.th**", timeout=20_000)
                logger.info(f"✅ SET login OK — URL: {self.page.url}")
                await self.page.wait_for_timeout(2000)
                return True
            except Exception:
                # ดู error message
                err_text = await self.page.evaluate(
                    "() => Array.from(document.querySelectorAll('.error, .alert, .text-danger, .invalid-feedback')).map(e => e.innerText?.trim()).filter(Boolean).join(' | ')"
                )
                self.last_error = err_text or f"SET login fail (URL: {self.page.url})"
                logger.warning(f"❌ SET login failed: {self.last_error}")
                await self._shot("set_login_failed")
                return False
        except Exception as e:
            self.last_error = f"SET login exception: {e}"
            logger.exception("❌ SET login exception")
            return False

    async def login(self, nid: str, pwd: str) -> bool:
        """Login เข้า DSL portal (Angular SPA) คืน True ถ้าสำเร็จ"""
        try:
            logger.info(f"🔑 goto {LOGIN_URL}")
            await self.page.goto(LOGIN_URL, wait_until="networkidle", timeout=30_000)
            await self.page.wait_for_selector("#citizenFld", timeout=15_000)
            await self._shot("01_login_loaded")

            # ปิด pop-up ประกาศข่าว ถ้ามี (login page — Escape ปลอดภัย)
            await self._dismiss_popups(allow_escape=True)
            await self._shot("01b_popup_closed")

            logger.info(f"⌨️  type NID ({len(nid)} chars)")
            await self.page.click("#citizenFld")
            await self.page.type("#citizenFld", nid, delay=30)

            logger.info(f"⌨️  type password ({len(pwd)} chars)")
            await self.page.click("#passwordFld")
            await self.page.type("#passwordFld", pwd, delay=30)
            await self._shot("02_filled")

            logger.info("🖱  click signInBtn")
            await self.page.click("#signInBtn")
            await self.page.wait_for_timeout(2000)
            await self._shot("03_after_click")

            # รอ URL เปลี่ยนออกจาก /rms-login (สำเร็จ) หรือพบ error message
            try:
                await self.page.wait_for_function(
                    "() => !location.hash.includes('rms-login')",
                    timeout=15_000,
                )
                logger.info(f"✅ logged in — URL: {self.page.url}")
                await self._shot("04_logged_in")
                return True
            except Exception:
                # ดู error message บนหน้า
                err_text = await self.page.evaluate("""() => {
                    const errs = document.querySelectorAll('.error, .alert, .text-danger, [class*="error"]');
                    return Array.from(errs).map(e => e.innerText?.trim()).filter(Boolean).join(' | ');
                }""")
                self.last_error = err_text or "ไม่สามารถ login ได้ (URL ไม่เปลี่ยน)"
                logger.warning(f"❌ login failed: {self.last_error}")
                await self._shot("04_login_failed")
                return False
        except Exception as e:
            self.last_error = f"login exception: {e}"
            logger.exception("❌ login exception")
            await self._shot("99_exception")
            return False

    async def fetch_courses(self) -> List[Dict]:
        """ดึงหลักสูตรที่ user ยังไม่ได้ทำจาก SET e-learning

        Flow:
          1. SSO DSL → SET (retry สูงสุด 2 ครั้ง — attempt 1 มัก fail เพราะ Angular ช้า)
          2. Navigate /list + verify URL
          3. Paginate ทุก page, scrape card-course
          4. Dedupe by id
          5. _filter_incomplete (API verify status ทุก course)
        """
        import json as _json
        import re as _re

        # ── 1. SSO retry ──
        sso_ok = False
        for attempt in range(2):
            logger.info(f"🔍 SSO DSL → SET (attempt {attempt + 1}/2)")
            sso_ok = await self._sso_click_and_capture()
            if sso_ok:
                break
            logger.warning(f"   SSO attempt {attempt + 1} fail — รอ 3s แล้วลองอีก")
            await self.page.wait_for_timeout(3000)
        logger.info(f"   SSO: {'✅' if sso_ok else '⚠️ ทุก attempt fail — ลอง goto ตรง'}")

        if sso_ok:
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=20_000)
            except Exception:
                pass
            await self.page.wait_for_timeout(1500)

        # รอให้ landing page settle
        logger.info(f"⏳ landing page: {self.page.url}")
        await self.page.wait_for_timeout(2000)
        await self._shot("05_set_landing")

        # ปิด popup บน SET (Angular state OK หลังโหลดเสร็จ → ห้าม Escape)
        await self._dismiss_popups(allow_escape=False)

        # ── 2. Iterate ทุกแท็บใน sidebar (กัน bug แท็บ "ทั้งหมด" ไม่ครบ) ──
        all_courses = []
        MAX_PAGES = 20  # safety guard ต่อแท็บ

        for tab_name, tab_url in SET_CATEGORY_URLS:
            logger.info(f"🌐 [tab={tab_name}] navigate → {tab_url}")
            try:
                await self.page.goto(tab_url, wait_until="domcontentloaded", timeout=30_000)
                await self.page.wait_for_timeout(1500)
            except Exception as e:
                logger.warning(f"⚠️  [tab={tab_name}] navigate fail: {e} — skip")
                await self._shot(f"06_{tab_name}_nav_fail")
                continue

            # รอ course cards render — ถ้าไม่มีก็ skip แท็บนี้
            try:
                await self.page.wait_for_selector("a.card-course", timeout=12_000)
            except Exception:
                logger.warning(f"⚠️  [tab={tab_name}] ไม่พบ card-course ใน 12s — แท็บอาจว่าง")
                await self._shot(f"06_{tab_name}_no_cards")
                continue
            await self.page.wait_for_timeout(1200)

            # paginate + scrape ภายในแท็บ
            page_num = 1
            seen_urls = set()
            tab_courses = []
            while page_num <= MAX_PAGES:
                await self._shot(f"06_{tab_name}_p{page_num}")
                page_courses = await self._scrape_current_page()
                logger.info(f"📄 [tab={tab_name}] หน้า {page_num} — เจอ {len(page_courses)} courses")
                tab_courses.extend(page_courses)

                cur_url = self.page.url
                if cur_url in seen_urls:
                    logger.warning(f"⚠️  [tab={tab_name}] URL ซ้ำ ({cur_url}) — หยุด pagination")
                    break
                seen_urls.add(cur_url)

                has_next = await self._goto_next_page()
                if not has_next:
                    break
                page_num += 1
                await self.page.wait_for_timeout(1500)

            if page_num > MAX_PAGES:
                logger.warning(f"⚠️  [tab={tab_name}] ชน MAX_PAGES={MAX_PAGES}")

            logger.info(f"📊 [tab={tab_name}] รวม {len(tab_courses)} courses จาก {page_num} หน้า")
            all_courses.extend(tab_courses)

        courses = all_courses
        logger.info(f"📊 รวมทุกแท็บ {len(courses)} courses (ก่อน dedupe)")

        # Save scraped raw data ในโหมด debug
        if DEBUG:
            try:
                dump_path = Path(SHOT_DIR) / "scraped_courses.json"
                dump_path.write_text(
                    _json.dumps(courses, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"  💾 raw scraped saved → {dump_path}")
            except Exception as e:
                logger.warning(f"  save scraped dump err: {e}")

        # ── 4. Dedupe ──
        seen, unique = set(), []
        for c in courses:
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            c["price"] = max(1, round(c["hours"] * PRICE_PER_HOUR))
            unique.append(c)

        logger.info(f"📊 {len(unique)} courses หลัง dedupe — กำลัง filter ที่เสร็จแล้วออก...")

        # ── 5. Filter via API ──
        incomplete = await self._filter_incomplete(unique)
        logger.info(f"✨ ส่งกลับ {len(incomplete)} courses (ยังไม่เสร็จ / ยังไม่ลงทะเบียน)")
        return incomplete

    async def _filter_incomplete(self, courses: List[Dict]) -> List[Dict]:
        """Filter คอร์สที่ user ยังไม่ได้ใบวุฒิบัตร — รวมทั้ง catalog ที่ยังไม่ลงทะเบียน

        Primary completion indicator: `certificate_datetime` (ได้ cert แล้ว = จบ)
        แหล่งข้อมูล: API ของ SET (ไม่ใช่ HTML hint จาก card — เก่ามี false-positive)

        Logic:
          certificate_datetime != null        → ได้ cert แล้ว → exclude
          enroll_id != null + cert == null    → ลงทะเบียนแล้ว ยังไม่จบ → include
            ├─ pct == 0   → status="not_started"
            └─ pct > 0    → status="in_progress"
          enroll_id == null + cert == null    → catalog ยังไม่ลงทะเบียน → include
            └─ status="not_enrolled" (automation จะ auto-enroll ตอนเริ่มงาน)

        Debug: เมื่อ DSL_DEBUG=1 → save status_map ไป {SHOT_DIR}/filter_status_map.json
        """
        import json as _json

        BATCH = 10  # fetch พร้อมกันทีละ 10

        # Log HTML hint (สำหรับ debug) — แต่ไม่ใช้ skip course
        hint_count = 0
        for c in courses:
            if c.get("card_completed_hint"):
                hint_count += 1
                logger.debug(
                    f"  ℹ️  hint: {c.get('code')} ดู complete จาก HTML "
                    f"(reason={c.get('_hint_reason')}) — verify ผ่าน API"
                )
        if hint_count:
            logger.info(f"  ℹ️  HTML hint: {hint_count}/{len(courses)} courses look complete — verify ทุกตัวผ่าน API")

        # ── Batch API calls — verify status ทุกคอร์ส ──
        status_map: Dict[str, Dict] = {}
        api_ids = [c["id"] for c in courses]
        for i in range(0, len(api_ids), BATCH):
            batch = api_ids[i:i + BATCH]
            batch_n = i // BATCH + 1
            try:
                results = await self.page.evaluate("""async (batch) => {
                    const TIMEOUT = 15000;
                    const fetchT = (url, opts) => {
                        const ctrl = new AbortController();
                        const tid = setTimeout(() => ctrl.abort(), TIMEOUT);
                        return fetch(url, {...opts, signal: ctrl.signal})
                            .finally(() => clearTimeout(tid));
                    };
                    const results = await Promise.all(batch.map(async id => {
                        try {
                            const r = await fetchT(
                                `/api/site/groups/SETStudentLoan/courses/${id}`,
                                { headers: { 'X-Requested-With': 'XMLHttpRequest' },
                                  credentials: 'include' }
                            );
                            if (!r.ok) {
                                return { id: String(id), enroll_id: null, pct: null, cert: null,
                                         err: `course HTTP ${r.status}` };
                            }
                            const d = await r.json();
                            const enrollId = d.enroll_id || null;
                            let pct = null, cert = null;
                            if (enrollId) {
                                const er = await fetchT(
                                    `/api/site/enroll/${enrollId}`,
                                    { headers: { 'X-Requested-With': 'XMLHttpRequest' },
                                      credentials: 'include' }
                                );
                                if (er.ok) {
                                    const ed = await er.json();
                                    pct = ed.learning_percentage ?? null;
                                    cert = ed.certificate_datetime ?? null;
                                } else {
                                    return { id: String(id), enroll_id: enrollId, pct: null, cert: null,
                                             err: `enroll HTTP ${er.status}` };
                                }
                            }
                            return { id: String(id), enroll_id: enrollId, pct, cert };
                        } catch(e) {
                            return { id: String(id), enroll_id: null, pct: null, cert: null,
                                     err: String(e.message || e).slice(0, 100) };
                        }
                    }));
                    return results;
                }""", batch)
                for r in results:
                    status_map[r["id"]] = r
                logger.debug(f"  batch {batch_n}: {len(results)} results")
            except Exception as e:
                logger.warning(f"  batch {batch_n} (ids={batch}) raised: {e}")

        # ── Save debug dump ──
        if DEBUG:
            try:
                dump_path = Path(SHOT_DIR) / "filter_status_map.json"
                dump_path.write_text(
                    _json.dumps(status_map, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"  💾 status_map saved → {dump_path}")
            except Exception as e:
                logger.warning(f"  save status dump err: {e}")

        # ── คืนทุกคอร์สที่ยังไม่มี cert (รวม catalog ยังไม่ลงทะเบียน) ──
        incomplete = []
        certified = 0
        unknown = 0
        errors_seen: Dict[str, int] = {}
        for c in courses:
            s = status_map.get(str(c["id"]), {})
            if not s:
                logger.warning(f"  ⚠️  unknown status {c.get('code')} (id={c['id']}) — batch missed, skip")
                unknown += 1
                continue
            err = s.get("err")
            if err:
                # นับ error types เพื่อ summary
                errors_seen[err] = errors_seen.get(err, 0) + 1
                logger.warning(f"  ⚠️  API err {c.get('code')}: {err}")
                # ใส่ใน list ไว้ก่อน — ดีกว่าทิ้ง (user เลือกได้)
            enroll_id = s.get("enroll_id")
            pct = s.get("pct")
            cert = s.get("cert")
            if cert:
                logger.info(f"  ⏭️  skip {c.get('code')} (cert issued {cert})")
                certified += 1
                continue
            if enroll_id:
                c["status"] = "in_progress" if pct else "not_started"
                c["enroll_id"] = enroll_id
                c["progress"] = pct
            else:
                c["status"] = "not_enrolled"
            incomplete.append(c)

        logger.info(
            f"✓ incomplete: {len(incomplete)} "
            f"(certified: {certified}, unknown: {unknown}, "
            f"hints_overridden: {sum(1 for c in incomplete if c.get('card_completed_hint'))})"
        )
        if errors_seen:
            logger.warning(f"  API errors summary: {errors_seen}")
        return incomplete

    async def _scrape_current_page(self) -> List[Dict]:
        """ดึงข้อมูล course card จากหน้าปัจจุบัน

        completion hint จาก HTML — เป็นแค่ HINT (logged เพื่อ debug) ไม่ใช้ skip
        ใช้ API ใน _filter_incomplete เป็น source of truth แทน
        (เก่ามี false-positive จากคำว่า 'ผ่าน'/'เสร็จ'/'ได้รับ' ที่อยู่ใน title คอร์ส)"""
        return await self.page.evaluate("""() => {
            // เฉพาะ marker ที่ชัดเจน (ไม่ใช้ ผ่าน/เสร็จ/ได้รับ เพราะ false-positive สูง)
            const SPECIFIC_MARKERS = ['วุฒิบัตร','certificate','completed'];
            return Array.from(document.querySelectorAll('a.card-course, a.a-card-embossed.card-course'))
                .map(card => {
                    const url = card.href || '';
                    const idMatch = url.match(/courses\\/(\\d+)/);
                    const text = card.innerText || '';
                    const html = card.innerHTML || '';
                    const lines = text.split('\\n').map(l => l.trim()).filter(Boolean);
                    const code = lines[0] || '';
                    const hoursLine = lines[1] || '';
                    const title = lines[2] || lines[1] || '';
                    let hours = 0;
                    const hMatch = hoursLine.match(/(\\d+)\\s*ชั่วโมง/);
                    const mMatch = hoursLine.match(/(\\d+)\\s*นาที/);
                    if (hMatch) hours += parseFloat(hMatch[1]);
                    if (mMatch) hours += parseInt(mMatch[1]) / 60;
                    hours = Math.round(hours * 10) / 10;
                    // เก็บ hint แค่จาก class เฉพาะ + คำ marker ที่ไม่ ambiguous
                    // (เก่าใช้ [class*="complet"] ที่ match completion-tracker UI feature ด้วย → ลบทิ้ง)
                    const lowerText = text.toLowerCase();
                    const has_specific_word = SPECIFIC_MARKERS.some(w => lowerText.includes(w));
                    const has_done_class = card.classList.contains('completed')
                        || card.classList.contains('course-completed');
                    const has_done_badge = !!card.querySelector(
                        '.badge-completed, .icon-completed, .badge-certificate, .icon-certificate'
                    );
                    const card_completed_hint = has_specific_word || has_done_class || has_done_badge;
                    return {
                        id: idMatch ? idMatch[1] : code,
                        code, title, hours, url, card_completed_hint,
                        _hint_reason: card_completed_hint
                            ? [has_specific_word && 'word', has_done_class && 'class', has_done_badge && 'badge']
                                .filter(Boolean).join('+')
                            : null,
                    };
                })
                .filter(c => c.id && c.title && c.hours > 0);
        }""")

    async def _goto_next_page(self) -> bool:
        """กดไปหน้าถัดไป — คืน False ถ้าไม่มีหน้าถัดไป"""
        # ลอง next button หลายแบบที่เห็นใน Bootstrap pagination
        next_selectors = [
            '.pagination a[rel="next"]',
            '.pagination li.next:not(.disabled) a',
            '.pagination a:has-text("Next")',
            '.pagination a[aria-label="Next"]',
            '.pagination button[aria-label="Next"]',
            'a.page-link[aria-label="Next"]',
        ]

        for sel in next_selectors:
            try:
                loc = self.page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=500):
                    # เช็คว่าไม่ถูก disabled
                    disabled = await loc.first.evaluate("el => el.closest('.disabled') !== null || el.disabled || el.getAttribute('aria-disabled')==='true'")
                    if disabled:
                        return False
                    await loc.first.scroll_into_view_if_needed()
                    await loc.first.click()
                    try:
                        await self.page.wait_for_selector("a.card-course", timeout=10_000)
                    except Exception:
                        await self.page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue

        # fallback — หา link ที่มี text เป็น page number ถัดไป
        try:
            current = await self.page.evaluate("""() => {
                const a = document.querySelector('.pagination .active a, .pagination li.active');
                return a ? parseInt(a.innerText.trim()) : null;
            }""")
            if current:
                next_num = str(current + 1)
                next_link = self.page.locator(f'.pagination a:has-text("{next_num}")')
                if await next_link.count() > 0:
                    await next_link.first.click()
                    try:
                        await self.page.wait_for_selector("a.card-course", timeout=10_000)
                    except Exception:
                        await self.page.wait_for_timeout(1500)
                    return True
        except Exception:
            pass

        return False

    # ──────────────────────── Watch flow ────────────────────────

    async def _sso_click_and_capture(self) -> bool:
        """คลิก SET e-Learning บน DSL portal แล้วจับ tab ใหม่ที่ Angular เปิด
        คืน True ถ้าสำเร็จและ self.page เปลี่ยนเป็น SET tab แล้ว"""
        # หา routeSETBtn เฉพาะเจาะจงก่อน แล้ว fallback ไป text selector
        set_link = self.page.locator('#routeSETBtn')
        if await set_link.count() == 0:
            set_link = self.page.locator(
                'a:has-text("SET e-Learning"), a:has-text("SET e-learning"), '
                'a:has-text("Set e-learning"), a:has-text("set e-learning")'
            )
        if await set_link.count() == 0:
            logger.warning("⚠️  ไม่พบ SET e-Learning link บนหน้า DSL")
            return False

        ctx = self.page.context
        # รอให้ Angular render click handler เสร็จ (ไม่ dismiss popup ก่อน — Escape รบกวน Angular state)
        await self.page.wait_for_timeout(2000)

        try:
            # DSL Angular เรียก SetLogin API (~1-2s) แล้วถึงเปิด tab — timeout 30s
            async with ctx.expect_page(timeout=30_000) as new_info:
                await set_link.first.click()
                # asyncio.sleep ให้ event loop yield โดยไม่ขึ้นกับ self.page state
                await asyncio.sleep(5)
            self.page = await new_info.value
            logger.info(f"✅ SSO tab เปิดแล้ว: {self.page.url}")
            return True
        except Exception as e:
            logger.warning(f"⚠️  SSO tab ไม่เปิดภายใน 30s: {e}")
            return False

    async def goto_set(self) -> bool:
        """SSO จาก DSL portal ไป SET e-learning landing
        เรียกหลัง login สำเร็จ ก่อน watch_course/fetch_courses
        คืน True ถ้า session ถึง SET แล้ว"""
        await self._sso_click_and_capture()

        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(1500)
        await self._dismiss_popups()
        # ยืนยันโดยไปหน้า /list หนึ่งครั้ง — ถ้า redirect กลับแปลว่า SSO พัง
        await self.page.goto(SET_LIST_URL, wait_until="domcontentloaded", timeout=30_000)
        await self.page.wait_for_timeout(1500)
        return "/list" in self.page.url

    async def complete_course_via_api(
        self,
        course_id: str,
        on_log: Optional[LogFn] = None,
        cert_dir: Optional[Path] = None,
        job_id: str = "",
    ) -> Optional[str]:
        """ทำคอร์สให้จบผ่าน API โดยตรง — ไม่ต้องเล่นวิดีโอจริง
        ขั้นตอน: enroll → navigate topics (JS auto-mark) → quiz → cert
        คืน path ของ PDF cert"""
        log = on_log or (lambda *a, **k: asyncio.sleep(0))
        if job_id:
            self._job_id = job_id
        await log("sys", f"เริ่มคอร์ส {course_id} (API mode)", None)

        # ── helper: GET CSRF token จาก cookie ─────────────────────
        def _js_headers() -> str:
            return """(() => {
                const xsrf = document.cookie.split(';').map(c => c.trim().split('=')).find(([k]) => k === 'XSRF-TOKEN');
                return {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json',
                    'X-XSRF-TOKEN': xsrf ? decodeURIComponent(xsrf[1]) : '',
                };
            })()"""

        # ── 1. ดึง course info + enroll_id ────────────────────────
        await log("sys", "ดึงข้อมูลคอร์ส...", "5")
        course_data = await self.page.evaluate(f"""async () => {{
            const r = await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}',
                {{ headers: {_js_headers()}, credentials: 'include' }});
            return r.json();
        }}""")
        title = course_data.get("title", course_id)
        enroll_id = course_data.get("enroll_id")
        await log("sys", f"หลักสูตร: {title}", "8")

        # ── 2. Enroll ถ้ายังไม่ได้ลงทะเบียน ─────────────────────
        if not enroll_id:
            await log("sys", "ลงทะเบียนคอร์ส...", "10")
            enroll_result = await self.page.evaluate(f"""async () => {{
                const headers = {_js_headers()};
                headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8';
                const r = await fetch('/api/site/enroll2learning', {{
                    method: 'POST',
                    headers,
                    credentials: 'include',
                    body: 'cid={course_id}&tid=&type=&pid=&ftype=',
                }});
                return {{ status: r.status, data: await r.json().catch(() => ({{}})) }};
            }}""")
            if enroll_result["status"] != 200:
                raise RuntimeError(f"enroll failed: {enroll_result['status']} — {enroll_result.get('data')}")
            # ดึง enroll_id ใหม่
            course_data = await self.page.evaluate(f"""async () => {{
                const r = await fetch('/api/site/groups/SETStudentLoan/courses/{course_id}',
                    {{ headers: {_js_headers()}, credentials: 'include' }});
                return r.json();
            }}""")
            enroll_id = course_data.get("enroll_id")
            if not enroll_id:
                raise RuntimeError("ลงทะเบียนแล้วแต่ไม่ได้ enroll_id")
            await log("ok", "ลงทะเบียนสำเร็จ", "12")

        # ── 3. ดึงรายการ topics ────────────────────────────────────
        await log("sys", "ดึงรายการ topics...", "15")
        enroll_data = await self.page.evaluate(f"""async () => {{
            const r = await fetch('/api/site/enroll/{enroll_id}',
                {{ headers: {_js_headers()}, credentials: 'include' }});
            return r.json();
        }}""")

        # แตก topics ทุกตัว (nested: parent → children)
        topics = []
        def _extract_topics(nodes):
            for node in (nodes or []):
                children = node.get("parent", [])
                if isinstance(children, list) and children:
                    _extract_topics(children)
                else:
                    # leaf node = actual video topic
                    e2t = node.get("enroll2topic") or {}
                    topics.append({
                        "id": node["id"],
                        "title": node.get("title", f"topic {node['id']}"),
                        "enroll2topic_id": e2t.get("id"),
                        "percentage": int(node.get("percentage") or 0),
                        "state": node.get("state", "vod"),
                    })
        _extract_topics(enroll_data.get("topics") or [])

        incomplete = [t for t in topics if t["percentage"] < 100 and t["state"] == "vod"]
        await log("sys", f"topics ทั้งหมด {len(topics)} | ยังไม่เสร็จ {len(incomplete)}", "18")

        # ── 4. Mark complete ผ่าน API จริง (เลียนแบบ JS ของ SET) ──
        # Flow: enroll2topic_stage → enroll/views → refetch → duration → status
        total = max(len(incomplete), 1)
        for i, topic in enumerate(incomplete, 1):
            pct = str(int(15 + (i / total) * 55))
            name = topic["title"][:50]
            await log("play", f"topic {i}/{total}: {name}", pct)

            tid = topic["id"]
            e2t_id = topic.get("enroll2topic_id")

            # ถ้ายังไม่มี enroll2topic_id → POST stage เพื่อสร้าง
            if not e2t_id:
                await self.page.evaluate(f"""async () => {{
                    const h = {_js_headers()};
                    h['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8';
                    await fetch('/api/site/enroll2topic_stage', {{
                        method: 'POST', headers: h, credentials: 'include',
                        body: 'enroll={enroll_id}&topics={tid}',
                    }});
                }}""")

            # 1. POST enroll/views (สร้าง view + อาจ create enroll2topic record)
            await self.page.evaluate(f"""async () => {{
                const h = {_js_headers()};
                h['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8';
                await fetch('/api/site/enroll/views', {{
                    method: 'POST', headers: h, credentials: 'include',
                    body: 'id=&enroll_id={enroll_id}&topics_id={tid}&state=vod',
                }});
            }}""")

            # 2. Refetch enroll data → ดึง enroll2topic_id ล่าสุดของ topic นี้
            if not e2t_id:
                refetch = await self.page.evaluate(f"""async () => (await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}})).json()""")
                def find_e2t(nodes):
                    for n in (nodes or []):
                        if isinstance(n.get('parent'), list) and n.get('parent'):
                            r = find_e2t(n['parent'])
                            if r: return r
                        elif n.get('id') == tid:
                            return (n.get('enroll2topic') or {}).get('id')
                    return None
                e2t_id = find_e2t(refetch.get('topics') or [])

            if not e2t_id:
                logger.warning(f"  topic {tid}: ไม่ได้ enroll2topic_id หลัง stage+views")
                continue

            # 3. POST duration + status (mark complete!)
            result = await self.page.evaluate(f"""async () => {{
                const h = {_js_headers()};
                h['Content-Type'] = 'application/x-www-form-urlencoded; charset=UTF-8';
                const d = await fetch('/api/site/enroll2topic_duration', {{
                    method: 'POST', headers: h, credentials: 'include',
                    body: 'id={e2t_id}&duration=0',
                }});
                const s = await fetch('/api/site/enroll2topic_status', {{
                    method: 'POST', headers: h, credentials: 'include',
                    body: 'id={e2t_id}&status=1',
                }});
                return {{ dur: d.status, sta: s.status }};
            }}""")
            logger.info(f"  topic {tid} (e2t={e2t_id}) → dur={result['dur']} sta={result['sta']}")

        # ── 4b. Verify percentage ────────────────────────────────────
        check = await self.page.evaluate(f"""async () => (await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}})).json()""")
        new_topics: list = []
        def _collect(nodes):
            for n in (nodes or []):
                if isinstance(n.get('parent'), list) and n.get('parent'):
                    _collect(n['parent'])
                else:
                    new_topics.append(int(n.get('percentage') or 0))
        _collect(check.get('topics') or [])
        done_cnt = sum(1 for p in new_topics if p >= 100)
        await log("sys", f"หลัง mark: เสร็จ {done_cnt}/{len(new_topics)} topics", "70")

        # ── 5-7. แบบทดสอบ — ทำเฉพาะที่คอร์สมีจริง (อ่านจาก course_data) ──
        #   field pre_test/post_test/exam ใน course_data (null = คอร์สไม่มี → ข้าม
        #   กันเสีย ~33s/component รอ poll radio ที่ไม่มี). API ไม่ส่ง key → ทำตามเดิม
        def _has_component(key: str) -> bool:
            return key not in course_data or course_data.get(key) is not None

        if _has_component("pre_test"):
            await log("sys", "Pre-test...", "72")
            await self._submit_exam(enroll_id, "pre-test", course_id=str(course_id))

        if _has_component("post_test"):
            await log("sys", "Post-test...", "82")
            await self._submit_exam(enroll_id, "post-test", course_id=str(course_id))
        else:
            await log("sys", "คอร์สนี้ไม่มี Post-test — ข้าม", "82")

        if _has_component("exam"):
            await log("sys", "Examination...", "88")
            await self._submit_exam(enroll_id, "exam", course_id=str(course_id))
        else:
            await log("sys", "คอร์สนี้ไม่มี Examination — ข้าม", "88")

        # ── 7b. ทำ survey ในหน้า /summary ──────────────────────────
        await log("sys", "ทำแบบสอบถาม...", "90")
        try:
            # ตรวจ survey_datetime ก่อน — ถ้าทำแล้วไม่ทำซ้ำ (กัน duplicate trigger anti-cheat)
            already = await self.page.evaluate(f"""async () => {{
                try {{
                    const r = await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}});
                    const d = await r.json();
                    return !!d.survey_datetime;
                }} catch (e) {{ return false; }}
            }}""")
            if already:
                await log("ok", "แบบสอบถามทำไปแล้ว — ข้าม", "91")
            else:
                survey_ok = await self._submit_survey_on_summary(enroll_id)
                if survey_ok:
                    await log("ok", "ส่งแบบสอบถามแล้ว", "91")
                else:
                    await log("warn", "ไม่เจอ survey form (อาจไม่ require)", "91")
        except Exception as e:
            logger.warning(f"  survey error: {e}")

        # ── 8. ขอวุฒิบัตร ──────────────────────────────────────────
        await log("sys", "ขอวุฒิบัตร...", "92")
        cert_path: Optional[str] = None
        if cert_dir is not None:
            cert_path = await self._request_and_download_cert(enroll_id, course_id, cert_dir)
            if cert_path:
                # ใช้ type 'ok' เพื่อกัน frontend setDone จาก log แต่ละ course
                # (type 'done' ใช้เฉพาะ "งานเสร็จสมบูรณ์" ใน tasks.py)
                await log("ok", "ได้วุฒิบัตรคอร์สนี้แล้ว", None)
            else:
                await log("warn", "คอร์สจบแล้ว แต่ยังดาวน์โหลดวุฒิบัตรไม่ได้", None)
        return cert_path

    # ── Answer cache: logic ย้ายไปที่ app/utils/answer_cache.py แล้ว ──
    # method ที่นี่เป็น thin wrapper เพื่อ backward compat กับ call site เดิม

    def _question_hash(self, text: str) -> str:
        from app.utils import answer_cache as _ac
        return _ac.question_hash(text)

    def _load_answer_cache(self) -> Dict[str, str]:
        from app.utils import answer_cache as _ac
        return _ac.load()

    def _save_answer_cache(self, new_entries: Dict[str, str]) -> None:
        from app.utils import answer_cache as _ac
        _ac.save(new_entries)

    async def _read_exam_dom(self) -> List[Dict]:
        """อ่าน question text + options จาก exam page ปัจจุบัน
        คืน [{q_name, q_text, options: [{value, text}]}]"""
        return await self.page.evaluate("""() => {
            const out = [];
            const seen = new Set();
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                if (seen.has(r.name)) return;
                seen.add(r.name);
                let parent = r.closest('.question, .form-group, .quiz-question, li, fieldset, .panel');
                if (!parent) parent = r.parentElement?.parentElement;
                const qNode = parent?.querySelector('legend, h3, h4, h5, .question-title, p:first-of-type, label');
                const qText = (qNode?.innerText || parent?.innerText || '').trim();
                const opts = [];
                document.querySelectorAll(`input[type="radio"][name="${r.name}"]`).forEach(opt => {
                    const lbl = opt.closest('label') || document.querySelector(`label[for="${opt.id}"]`);
                    opts.push({value: opt.value, text: (lbl?.innerText || '').trim().slice(0, 200)});
                });
                out.push({q_name: r.name, q_text: qText.slice(0, 500), options: opts});
            });
            return out;
        }""")

    async def _read_score_page(self, enroll_id: int, e2q_id: int) -> List[Dict]:
        """เปิดหน้า /score แล้ว extract เฉลย — คืน [{q_text, correct_value}] เท่าที่หาได้"""
        url = f"{SET_BASE}/enroll/{enroll_id}/exam/{e2q_id}/score"
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await self.page.wait_for_timeout(2_500)
        except Exception as e:
            logger.warning(f"  score page goto err: {e}")
            return []
        return await self.page.evaluate("""() => {
            // หา indicator ของคำตอบที่ถูก — class/icon ที่ SET ใช้แต่ละธีม
            const isCorrectMark = el => !!(el && (
                el.classList?.contains('correct') ||
                el.classList?.contains('text-success') ||
                el.classList?.contains('is-correct') ||
                el.classList?.contains('answer-correct') ||
                el.querySelector?.('.bi-check-circle, .fa-check, .text-success, [class*="correct"]')
            ));
            const out = [];
            const seen = new Set();
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                if (seen.has(r.name)) return;
                seen.add(r.name);
                // หา radio ที่ "ถูก" ของ group นี้
                let correctValue = null;
                document.querySelectorAll(`input[type="radio"][name="${r.name}"]`).forEach(opt => {
                    const lbl = opt.closest('label') || document.querySelector(`label[for="${opt.id}"]`);
                    if (isCorrectMark(lbl) || isCorrectMark(opt.parentElement)) {
                        correctValue = opt.value;
                    }
                });
                if (correctValue == null) return;  // หาเฉลยไม่ได้สำหรับข้อนี้
                let parent = r.closest('.question, .form-group, .quiz-question, li, fieldset, .panel');
                if (!parent) parent = r.parentElement?.parentElement;
                const qNode = parent?.querySelector('legend, h3, h4, h5, .question-title, p:first-of-type, label');
                const qText = (qNode?.innerText || parent?.innerText || '').trim();
                out.push({q_text: qText.slice(0, 500), correct_value: correctValue});
            });
            return out;
        }""")

    async def _submit_exam(self, enroll_id: int, exam_type: str, course_id: str = "", cache_only: bool = False) -> None:
        """ทำ exam ผ่าน API — อ่านเฉลยจาก score page หลัง submit เพื่อ cache คำตอบ
        เพื่อให้ attempt ถัดไปใช้คำตอบที่ถูกได้ (กัน SET randomize per attempt)"""
        # type values (ตรวจสอบจาก cert response field mapping):
        # type=1 → pre_test_percentage
        # type=3 → exam_percentage (ทั้งที่ชื่อ "post-test")
        # type=4 → post_test_percentage (ทั้งที่ชื่อ "exam")
        # type=5 → survey
        # เราเรียก URL /exam/post-test แต่จริงต้อง POST type=4 เพื่อ fill post_test_percentage
        type_n = {"pre-test": 1, "post-test": 4, "exam": 3}.get(exam_type, 3)

        exam_url = f"{SET_BASE}/enroll/{enroll_id}/exam/{exam_type}"
        await self.page.goto(exam_url, wait_until="domcontentloaded", timeout=30_000)
        await self.page.wait_for_timeout(5_000)

        # คลิก "เริ่มแบบทดสอบ" / "เริ่มทำแบบทดสอบ" ถ้ามี (สำคัญสำหรับ exam page)
        await self.page.evaluate("""() => {
            for (const el of document.querySelectorAll('button, a, .btn')) {
                const t = (el.innerText || '').trim();
                if (!t || t.length > 30) continue;
                if (t === 'เริ่มแบบทดสอบ' || t === 'เริ่มทำแบบทดสอบ' || t.startsWith('เริ่มทำ') || t.startsWith('เริ่มแบบ')) {
                    el.disabled = false;
                    el.click();
                    return;
                }
            }
        }""")
        await self.page.wait_for_timeout(3_000)

        # poll หา radio ทุก 1.5s สูงสุด 25s
        radios_found = 0
        for _ in range(17):
            radios_found = await self.page.evaluate(
                "() => document.querySelectorAll('input[type=\"radio\"]').length"
            )
            if radios_found > 0:
                break
            await self.page.wait_for_timeout(1_500)
        if radios_found == 0:
            logger.info(f"  {exam_type}: ไม่เจอ radio (รอ 25s แล้ว) — UI อาจถูก lock")
            return
        logger.info(f"  {exam_type}: เจอ {radios_found} radios")

        # ── 1. ดึง questions + answer options + quiz_id จาก HTML ──
        info = await self.page.evaluate("""() => {
            const qs = {};
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                if (!qs[r.name]) qs[r.name] = [];
                qs[r.name].push(r.value);
            });
            // หา quiz_id จากหลายแหล่ง
            let quizId = null;
            const el = document.querySelector('[data-quiz-id]');
            if (el) quizId = el.dataset.quizId;
            if (!quizId) {
                const inp = document.querySelector('input[name="qid"], input[name="quiz_id"]');
                if (inp) quizId = inp.value;
            }
            if (!quizId) {
                // จาก __INITIAL_STATE__ หรือ JS var
                const m = document.body.innerHTML.match(/quiz[_-]?id["':\s=]+(\d{3,6})/i);
                if (m) quizId = m[1];
            }
            return { questions: qs, quizId };
        }""")
        questions = info.get("questions") or {}
        quiz_id = info.get("quizId")
        if not questions:
            logger.info(f"  {exam_type}: ไม่มี radio — ข้าม")
            return
        if not quiz_id:
            logger.warning(f"  {exam_type}: หา quiz_id ไม่เจอ — ตอบมั่วครั้งเดียว")
            await self._dumb_submit_exam()
            return

        q_ids = list(questions.keys())
        opts = [questions[q] for q in q_ids]
        n = len(q_ids)
        logger.info(f"  {exam_type}: quiz_id={quiz_id} questions={n} (options/q: {[len(o) for o in opts]})")

        async def _submit(indices) -> tuple:
            """submit คำตอบตาม indices คืน (score, count, exam_status)"""
            # helper: fetch with 20s timeout via AbortController
            FETCH_TIMEOUT_MS = 20_000
            # 1. สร้าง enroll2quiz ใหม่ทุกครั้ง
            e2q_raw = await self.page.evaluate(f"""async () => {{
                const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
                const ctrl = new AbortController();
                const tid = setTimeout(() => ctrl.abort(), {FETCH_TIMEOUT_MS});
                try {{
                    const r = await fetch('/api/site/enroll2quiz', {{
                        method:'POST', headers:h, credentials:'include', signal:ctrl.signal,
                        body: 'eid={enroll_id}&qid={quiz_id}&type={type_n}',
                    }});
                    clearTimeout(tid);
                    const t = await r.text();
                    try {{ return JSON.parse(t); }} catch (e) {{ return {{__err: 'non_json', body: t.slice(0,80)}}; }}
                }} catch (e) {{ clearTimeout(tid); return {{__err: 'fetch_failed', msg: String(e)}}; }}
            }}""")
            if e2q_raw.get("__err"):
                logger.warning(f"  enroll2quiz failed: {e2q_raw}")
                return (0, n, 0, 0)
            e2q_id = e2q_raw.get("enroll2quiz")
            if not e2q_id:
                return (0, n, 0, 0)
            # 2. submit answers — fire-and-forget (ไม่ await response เพราะ server อาจ throttle)
            parts = [f"{q_ids[i]}={opts[i][indices[i]]}" for i in range(n)]
            parts += [f"enroll2quiz={e2q_id}", f"questionsCount={n}", "quiz2topic="]
            body = "&".join(parts)
            try:
                await self.page.evaluate(f"""() => {{
                    const h = {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}};
                    fetch('/api/site/questions2answer', {{
                        method:'POST', headers:h, credentials:'include',
                        body: {body!r},
                    }}).catch(() => {{}});
                }}""")
            except Exception as e:
                logger.warning(f"  questions2answer evaluate error: {e}")
            # รอให้ server บันทึก result ก่อน GET history
            await self.page.wait_for_timeout(3_000)
            # 3. GET history → match by enroll2quiz_id (retry 3x กัน timing race)
            hist_raw = None
            for _attempt in range(3):
                hist_raw = await self.page.evaluate(f"""async () => {{
                    const ctrl = new AbortController();
                    const tid = setTimeout(() => ctrl.abort(), {FETCH_TIMEOUT_MS});
                    try {{
                        const r = await fetch('/api/site/exam/{quiz_id}/history?page=1&per_page=10&enroll_id={enroll_id}', {{credentials:'include', signal:ctrl.signal}});
                        clearTimeout(tid);
                        const t = await r.text();
                        try {{ return JSON.parse(t); }} catch (e) {{ return null; }}
                    }} catch (e) {{ clearTimeout(tid); return null; }}
                }}""")
                data = (hist_raw or {}).get("data") or []
                if any(int(x.get("id") or 0) == int(e2q_id) for x in data):
                    break
                await self.page.wait_for_timeout(2_000)
            data = (hist_raw or {}).get("data") or []
            target = next((x for x in data if int(x.get("id") or 0) == int(e2q_id)), data[0] if data else None)
            if not target:
                return (0, n, 0, int(e2q_id))
            return (int(target.get("score") or 0), int(target.get("count") or n), int(target.get("exam_status") or 0), int(e2q_id))

        # ── Pre-test: ไม่ต้องผ่าน — submit ครั้งเดียวจบ ────────────
        if exam_type == "pre-test":
            s, t, _, _ = await _submit([0] * n)
            logger.info(f"  ✅ pre-test: submit {s}/{t} (ไม่ต้องผ่าน)")
            return

        PASS_PCT = 0.7

        def passed(s, t):
            return t > 0 and s / t >= PASS_PCT

        # ── LLM-first solver ──────────────────────────────
        # ลด MAX_ATTEMPTS เป็น 3 กัน anti-cheat trigger (SET ตั้ง certificate=False ถ้า submit เยอะ)
        from app.utils.llm_answer import answer_quiz
        cache = self._load_answer_cache()
        MAX_ATTEMPTS = _app_settings.dsl_max_exam_attempts
        best_score, best_total = 0, n
        best_indices = [0] * n
        exam_url = f"{SET_BASE}/enroll/{enroll_id}/exam/{exam_type}"

        async def _refresh_exam_page():
            """กลับไปหน้า exam หลังเข้าหน้า score แล้ว"""
            try:
                await self.page.goto(exam_url, wait_until="domcontentloaded", timeout=20_000)
                await self.page.wait_for_timeout(2_000)
                await self.page.evaluate("""() => {
                    for (const el of document.querySelectorAll('button, a, .btn')) {
                        const t = (el.innerText || '').trim();
                        if (t === 'เริ่มแบบทดสอบ' || t === 'เริ่มทำแบบทดสอบ' || t.startsWith('เริ่มทำ') || t.startsWith('เริ่มแบบ')) {
                            el.disabled = false; el.click(); return;
                        }
                    }
                }""")
                await self.page.wait_for_timeout(2_500)
            except Exception as e:
                logger.warning(f"  refresh exam page err: {e}")

        for attempt in range(MAX_ATTEMPTS):
            # อ่าน question text + options ปัจจุบัน
            qdata = await self._read_exam_dom()
            if not qdata:
                logger.warning(f"  attempt {attempt}: no questions read → fallback opt0")
                qdata = [{"q_name": qid, "q_text": "", "options": [{"value": v, "text": ""} for v in opts[i]]}
                         for i, qid in enumerate(q_ids)]

            # เลือกคำตอบ: 1) cache, 2) LLM, 3) rotation
            #   attempt 0: DeepSeek (primary) → Claude (API fallback)
            #   attempt 1: Claude ตรงๆ (second opinion ตอน attempt 0 ตอบผิด)
            #   attempt 2+: cache + rotation อย่างเดียว
            llm_indices = None
            # cache-first: ถ้าทุกข้ออยู่ใน cache แล้ว → ไม่ต้องเรียก LLM (ประหยัด cost + เร็ว)
            #   ข้อใหม่/คอร์สใหม่ (n_cache_miss > 0) → เรียก LLM ตามเดิมเพื่อเรียนรู้
            n_cache_miss = sum(1 for q in qdata if self._question_hash(q.get("q_text", "")) not in cache)
            if n_cache_miss == 0 and not cache_only and attempt == 0:
                logger.info(f"    ✅ cache ครบทุกข้อ ({len(qdata)} ข้อ) — ข้าม LLM (ไม่เสีย cost)")
            if attempt == 0 and not cache_only and n_cache_miss > 0:
                for _di, _dq in enumerate(qdata[:2]):
                    logger.info(f"    [DOM q{_di+1}] q_text={repr(_dq.get('q_text','')[:120])} opts={[o.get('text','')[:40] for o in _dq.get('options',[])[:4]]}")
                logger.info(f"    LLM: ถาม {len(qdata)} ข้อ (DeepSeek primary)…")
                llm_indices = await answer_quiz(qdata)
                if llm_indices is not None:
                    logger.info(f"    LLM: ได้คำตอบ {llm_indices}")
                else:
                    logger.warning(f"    LLM: ตอบไม่ได้ → fallback rotation")
            elif attempt == 1 and not cache_only and n_cache_miss > 0:
                logger.info(f"    LLM: ถาม {len(qdata)} ข้อ (Claude — second opinion)…")
                llm_indices = await answer_quiz(qdata, force_provider="claude")
                if llm_indices is not None:
                    logger.info(f"    LLM/Claude: ได้คำตอบ {llm_indices}")
                else:
                    logger.warning(f"    LLM/Claude: ตอบไม่ได้ → fallback rotation")

            indices = []
            known_count = 0
            fallback_text_count = 0
            import hashlib as _h
            import json as _j

            def _text_hash(t: str) -> str:
                return _h.sha1(" ".join((t or "").split()).encode("utf-8")).hexdigest()[:8]

            for i, q in enumerate(qdata):
                qh = self._question_hash(q["q_text"])
                idx = None
                if qh and qh in cache:
                    cached_raw = cache[qh]
                    # Support 2 formats:
                    #   (legacy) plain string = option.value
                    #   (robust) JSON {"v": "...", "t": "<text_hash>"}
                    correct_v, correct_t = None, None
                    try:
                        parsed = _j.loads(cached_raw)
                        if isinstance(parsed, dict):
                            correct_v = parsed.get("v")
                            correct_t = parsed.get("t")
                    except (ValueError, TypeError):
                        correct_v = cached_raw

                    # 1. ลอง match by value (เร็ว)
                    if correct_v is not None:
                        idx = next(
                            (oi for oi, o in enumerate(q["options"]) if str(o["value"]) == str(correct_v)),
                            None,
                        )
                    # 2. Fallback: match by text_hash (กัน SET random option.value)
                    if idx is None and correct_t:
                        idx = next(
                            (oi for oi, o in enumerate(q["options"]) if _text_hash(o.get("text", "")) == correct_t),
                            None,
                        )
                        if idx is not None:
                            fallback_text_count += 1

                    if idx is not None:
                        known_count += 1

                if idx is None:
                    if llm_indices is not None:
                        idx = llm_indices[i] % len(q["options"])
                    # else: ยังคง None → จะตรวจด้านล่าง
                indices.append(idx)

            if fallback_text_count > 0:
                logger.info(f"    cache: {fallback_text_count} ข้อใช้ text-hash fallback (option.value เปลี่ยน)")

            # ── ตรวจ cache miss ที่ไม่มี LLM — ห้ามเดา ──────────────
            missing_idx = [i for i, x in enumerate(indices) if x is None]
            # ── Record คำถามใหม่ที่ไม่อยู่ใน cache → pending_dump ──
            # ต้องบันทึก "ก่อน" guard ด้านล่าง ไม่งั้น continue จะข้าม
            try:
                from app.utils.pending_dump import record_questions
                unknown_qs = [q for q in qdata
                              if self._question_hash(q.get("q_text", "")) not in cache]
                if unknown_qs:
                    n_recorded = record_questions(
                        unknown_qs, set(cache.keys()),
                        course_id=str(course_id), exam_type=exam_type,
                    )
                    if n_recorded:
                        logger.info(f"    📝 record {n_recorded} ข้อใหม่ → pending_dump")
            except Exception as _e:
                logger.warning(f"    pending record fail: {_e}")

            # ไม่มี LLM ช่วย (cache_only TEST หรือ cache ครบแต่บาง entry map option ไม่ได้)
            #   → เติม option แรกแล้ว submit (กัน skip submit → 0 คะแนน) แทนการข้าม
            if (cache_only or n_cache_miss == 0) and missing_idx:
                for i in missing_idx:
                    indices[i] = 0
                tag = "cache-only" if cache_only else "cache-skip-LLM"
                logger.info(f"    [{tag}] เติม {len(missing_idx)} ข้อที่ map ไม่ได้ ด้วย option แรก แล้ว submit")
                missing_idx = []

            if missing_idx:
                missing_qs = [qdata[i].get("q_text", "")[:60] for i in missing_idx]
                logger.error(
                    f"  ❌ {exam_type} attempt {attempt}: "
                    f"{len(missing_idx)} ข้อไม่อยู่ใน cache และ LLM (DeepSeek/Claude) ตอบไม่ได้"
                )
                for mq in missing_qs:
                    logger.error(f"      ข้อที่ไม่รู้จัก: {mq!r}")

                # ── ถามคน: เขียนคำถามลง Redis รอ human ตอบ ──────────────
                if self._job_id:
                    human_answers = await self._ask_human_exam(
                        job_id=self._job_id,
                        course_id=str(course_id),
                        exam_type=exam_type,
                        attempt=attempt,
                        qdata=qdata,
                        missing_idx=missing_idx,
                    )
                    if human_answers:
                        # ใส่คำตอบจาก human ลงใน indices
                        for i, ans in enumerate(human_answers):
                            if i < len(indices):
                                indices[i] = ans
                        missing_idx = [i for i, x in enumerate(indices) if x is None]
                        if not missing_idx:
                            logger.info(f"  ✅ human ตอบครบ — ดำเนินการต่อ")
                        else:
                            logger.warning(f"  ⚠️  human ตอบไม่ครบ {len(missing_idx)} ข้อ — ข้าม")
                            if attempt < MAX_ATTEMPTS - 1:
                                await _refresh_exam_page()
                            continue
                    else:
                        logger.warning(f"  ⚠️  human ไม่ตอบภายใน timeout — ข้ามการ submit")
                        if attempt < MAX_ATTEMPTS - 1:
                            await _refresh_exam_page()
                        continue
                else:
                    if attempt < MAX_ATTEMPTS - 1:
                        await _refresh_exam_page()
                    continue

            # ใช้ q_ids/opts จาก _submit closure — ต้อง map ให้ตรง q_name
            # ถ้า DOM order ไม่ตรง q_ids ที่ extract ตอนแรก → ใช้ DOM order แทน
            if [q["q_name"] for q in qdata] == q_ids:
                submit_indices = indices
            else:
                # remap: หา index ใน q_ids ของแต่ละ q_name
                submit_indices = [0] * n
                for i, q in enumerate(qdata):
                    if q["q_name"] in q_ids:
                        submit_indices[q_ids.index(q["q_name"])] = indices[i]

            s, t, _, e2q_id = await _submit(submit_indices)
            logger.info(f"  attempt {attempt}: {s}/{t} (cache known: {known_count}/{n})")

            # ── Auto-save: ถ้าผ่าน 100% → คำตอบที่ใช้ทุกข้อต้องถูก → save เป็น trusted ──
            if s == t and t > 0:
                new_entries = {}
                for i, q in enumerate(qdata):
                    qh = self._question_hash(q.get("q_text", ""))
                    if not qh or qh in cache:
                        continue
                    if i >= len(indices) or indices[i] >= len(q.get("options", [])):
                        continue
                    chosen_opt = q["options"][indices[i]]
                    new_entries[qh] = _j.dumps({
                        "v": str(chosen_opt.get("value", "")),
                        "t": _text_hash(chosen_opt.get("text", "")),
                    }, ensure_ascii=False, separators=(",", ":"))
                if new_entries:
                    cache.update(new_entries)
                    self._save_answer_cache(new_entries)
                    logger.info(
                        f"    ✅ auto-save {len(new_entries)} เฉลยใหม่ (perfect score) → answer_bank"
                    )

            if s > best_score:
                best_score = s
                best_total = t
                best_indices = list(submit_indices)

            if passed(s, t):
                logger.info(f"  ✅ {exam_type}: ผ่าน ({s}/{t} = {s/t:.0%})")
                return

            # เปิดหน้า score แล้ว extract เฉลย
            if e2q_id:
                truth = await self._read_score_page(enroll_id, e2q_id)
                logger.info(f"    score page: พบเฉลย {len(truth)} ข้อ (จาก {n} ข้อทั้งหมด)")
                if truth:
                    for _ti, _tr in enumerate(truth[:2]):
                        logger.info(f"    [score q{_ti+1}] q_text={repr((_tr.get('q_text') or '')[:80])} correct={_tr.get('correct_value')}")
                truth_new: Dict[str, str] = {}
                for item in truth:
                    qh = self._question_hash(item.get("q_text") or "")
                    correct = item.get("correct_value")
                    if qh and correct and cache.get(qh) != correct:
                        cache[qh] = correct
                        truth_new[qh] = correct
                if truth_new:
                    self._save_answer_cache(truth_new)
                    logger.info(f"    cache: เพิ่ม {len(truth_new)} เฉลยใหม่ (total {len(cache)})")
                else:
                    logger.info(f"    cache: score page ไม่แสดงเฉลย — ลอง random ต่อ")

            # กลับไปหน้า exam ก่อน attempt ถัดไป
            if attempt < MAX_ATTEMPTS - 1:
                await _refresh_exam_page()

        # ─── Final submit ด้วย best combination ───
        logger.warning(f"  ⚠️  {exam_type}: best {best_score}/{best_total} = {best_score/best_total*100:.0f}% — ยังไม่ผ่าน 70%")

    async def _ask_human_exam(
        self,
        job_id: str,
        course_id: str,
        exam_type: str,
        attempt: int,
        qdata: list,
        missing_idx: list,
    ):
        """เขียนคำถามที่ไม่รู้คำตอบลง Redis → subscribe channel รอ human ตอบผ่าน Dashboard
        คืน list[int] (0-based indices) หรือ None ถ้า timeout"""
        import json as _json
        import time as _time

        import redis as _sync_redis
        from app.config import settings as _s

        r = None
        pubsub = None
        redis_key = f"exam:human:{job_id}:{course_id}"
        answer_key = f"exam:human:answer:{job_id}:{course_id}"
        channel = f"exam:human:ch:{job_id}:{course_id}"

        try:
            r = _sync_redis.from_url(_s.redis_url, decode_responses=True)

            # ลบ answer เก่าก่อน (กัน leftover)
            r.delete(answer_key)

            # เขียนคำถามทั้งหมด (ไม่ใช่แค่ missing) เพื่อให้ human เห็น context
            payload = {
                "job_id": job_id[:8],
                "course_id": course_id,
                "exam_type": exam_type,
                "attempt": attempt,
                "n_questions": len(qdata),
                "missing_idx": missing_idx,
                "questions": [
                    {
                        "idx": i,
                        "q_text": q.get("q_text", ""),
                        "options": [o.get("text", o.get("value", "")) for o in (q.get("options") or [])],
                        "need_answer": i in missing_idx,
                    }
                    for i, q in enumerate(qdata)
                ],
                "expires_at": _time.time() + self._human_answer_timeout,
            }
            r.setex(redis_key, self._human_answer_timeout, _json.dumps(payload, ensure_ascii=False))
            logger.info(f"  🙋 รอ human ตอบ {len(missing_idx)} ข้อ ใน Dashboard (timeout {self._human_answer_timeout}s)")

            # Subscribe channel ก่อน — dashboard publish ทันทีหลัง user ตอบ
            pubsub = r.pubsub(ignore_subscribe_messages=True)
            pubsub.subscribe(channel)

            # เช็ค answer_key ครั้งแรกหลัง subscribe (กัน race: dashboard เขียน + publish ก่อน worker subscribe)
            raw = r.get(answer_key)
            if raw:
                answers = _json.loads(raw)
                logger.info(f"  ✅ human ตอบแล้ว (immediate): {answers}")
                return answers

            # Loop: รอ pubsub message (wake-up signal) — fallback poll answer_key กัน publish miss
            deadline = _time.time() + self._human_answer_timeout
            while _time.time() < deadline:
                remaining = deadline - _time.time()
                wait_sec = min(10.0, max(0.1, remaining))
                # ใช้ pubsub.get_message ใน executor — wake ก่อนถ้า dashboard publish, ไม่งั้น block 10s
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda w=wait_sec: pubsub.get_message(timeout=w),
                )
                raw = r.get(answer_key)
                if raw:
                    try:
                        answers = _json.loads(raw)
                        logger.info(f"  ✅ human ตอบแล้ว: {answers}")
                        return answers
                    except Exception as je:
                        logger.warning(f"  answer JSON parse err: {je} — raw={raw[:100]!r}")
                        return None

            logger.warning(f"  ⏰ human ไม่ตอบภายใน {self._human_answer_timeout}s")
            return None

        except Exception as e:
            logger.warning(f"  _ask_human_exam error: {type(e).__name__}: {e}")
            return None
        finally:
            # Cleanup: ปิด pubsub + ลบ keys + ปิด client ทุกกรณี
            if pubsub is not None:
                try:
                    pubsub.unsubscribe(channel)
                    pubsub.close()
                except Exception:
                    pass
            if r is not None:
                try:
                    r.delete(redis_key, answer_key)
                except Exception:
                    pass
                try:
                    r.close()
                except Exception:
                    pass

    async def _submit_survey_on_summary(self, enroll_id: int) -> bool:
        """ทำ survey ในหน้า /summary accordion:
        1. expand accordion → survey form แสดง
        2. เลือก radio ทุกข้อ
        3. คลิก '#submit-an-survey'
        4. คลิก 'ยืนยันการส่งแบบสอบถาม' ใน confirm popup
        5. ตรวจ survey_datetime != null
        คืน True ถ้าสำเร็จ, False ถ้าไม่มี survey form"""
        await self.page.goto(
            f"{SET_BASE}/enroll/{enroll_id}/summary",
            wait_until="domcontentloaded", timeout=30_000,
        )
        await self.page.wait_for_timeout(2_000)

        # expand ทุก accordion → render survey form
        await self.page.evaluate("""() => {
            document.querySelectorAll('.collapse').forEach(c => {
                c.classList.add('show');
                c.style.display = 'block';
                c.style.height = 'auto';
                c.style.visibility = 'visible';
            });
        }""")
        await self.page.wait_for_timeout(1_500)

        # เลือก radio + enable submit button
        radio_count = await self.page.evaluate("""() => {
            const form = document.querySelector('#survey-form');
            if (!form) return 0;
            const groups = new Set();
            let count = 0;
            form.querySelectorAll('input[type="radio"]').forEach(r => {
                if (!groups.has(r.name)) {
                    groups.add(r.name);
                    r.checked = true;
                    ['change','input','click'].forEach(ev =>
                        r.dispatchEvent(new Event(ev, {bubbles:true})));
                    count++;
                }
            });
            const btn = document.querySelector('#submit-an-survey');
            if (btn) btn.disabled = false;
            return count;
        }""")
        if radio_count == 0:
            logger.info("  survey: ไม่เจอ form (course นี้อาจไม่ require)")
            return False
        logger.info(f"  survey: เลือก radio {radio_count} ข้อ")
        await self.page.wait_for_timeout(800)

        # คลิกผ่าน JS .click() — ข้าม Playwright visibility check
        clicked = await self.page.evaluate("""() => {
            const btn = document.querySelector('#submit-an-survey');
            if (!btn) return false;
            btn.disabled = false;
            // ทำ visible ทุก parent
            let el = btn;
            while (el && el !== document.body) {
                if (el.classList) el.classList.add('show');
                if (el.style) { el.style.display = ''; el.style.visibility = 'visible'; }
                el = el.parentElement;
            }
            btn.click();
            return true;
        }""")
        logger.info(f"  ส่งแบบสอบถาม JS click: {clicked}")
        await self.page.wait_for_timeout(3_000)

        # confirm popup "ยืนยันการส่งแบบสอบถาม" — popup เป็น modal Bootstrap
        confirmed = await self.page.evaluate("""() => {
            // หาปุ่มที่มี text "ยืนยัน" ใน modal/dialog
            const all = document.querySelectorAll('button, a, .btn');
            for (const el of all) {
                const t = (el.innerText || el.textContent || '').trim();
                if (t.includes('ยืนยันการส่งแบบสอบถาม') || t === 'ยืนยัน') {
                    el.click();
                    return t;
                }
            }
            return null;
        }""")
        logger.info(f"  ยืนยันการส่งแบบสอบถาม clicked: {confirmed}")
        await self.page.wait_for_timeout(6_000)

        # verify survey_datetime
        check = await self.page.evaluate(f"""async () => {{
            const r = await fetch('/api/site/enroll/{enroll_id}', {{credentials:'include'}});
            const d = await r.json();
            return d.survey_datetime;
        }}""")
        logger.info(f"  survey_datetime หลัง submit = {check}")
        return bool(check)

    async def _dumb_submit_exam(self) -> None:
        """fallback: เลือก radio แรกทุกข้อ + click submit"""
        await self.page.evaluate("""() => {
            const groups = new Set();
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                if (!groups.has(r.name)) {
                    groups.add(r.name);
                    r.checked = true;
                    ['change','input'].forEach(ev => r.dispatchEvent(new Event(ev,{bubbles:true})));
                }
            });
            const btn = document.querySelector('.submit-an-answer, button[type="submit"]');
            if (btn) { btn.disabled = false; btn.click(); }
        }""")
        await self.page.wait_for_timeout(3_000)

    async def _request_and_download_cert(
        self, enroll_id: int, course_id: str, cert_dir: Path
    ) -> Optional[str]:
        """ขอวุฒิบัตร + fetch PDF
        ถ้า cert ไม่ออกครั้งแรก → return None ให้ background retry task ลองใหม่"""
        import random
        cert_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = cert_dir / f"cert_{course_id}.pdf"

        # 1. Navigate summary (ให้ session อยู่ใน context cert)
        await self.page.goto(
            f"{SET_BASE}/enroll/{enroll_id}/summary",
            wait_until="domcontentloaded", timeout=30_000,
        )
        await self.page.wait_for_timeout(random.randint(1500, 2500))

        # expand ทุก accordion ก่อน — ปุ่มอาจอยู่ใน collapsed section
        await self.page.evaluate("""() => {
            document.querySelectorAll('.collapse').forEach(c => {
                c.classList.add('show');
                c.style.display = 'block';
                c.style.height = 'auto';
                c.style.visibility = 'visible';
            });
        }""")
        await self.page.wait_for_timeout(1_000)

        # 2. ถ้ามี surveyModal — ทำ survey + click submit (real user-like)
        btn_exists = await self.page.evaluate(
            "() => !!document.querySelector('.btn-download-certificate')"
        )
        logger.info(f"  ขอวุฒิบัตร: .btn-download-certificate exists={btn_exists}")
        await self.page.evaluate("""() => {
            const btn = document.querySelector('.btn-download-certificate');
            if (btn) {
                btn.disabled = false;
                btn.scrollIntoView({behavior: 'smooth', block: 'center'});
                btn.click();
            }
        }""")
        await self.page.wait_for_timeout(2_500)
        modal_visible = await self.page.evaluate(
            "() => { const m = document.querySelector('#surveyModal'); return m && m.classList.contains('show'); }"
        )
        logger.info(f"  surveyModal visible={modal_visible}")
        if modal_visible:
            await self.page.evaluate("""() => {
                const m = document.querySelector('#surveyModal');
                const groups = new Set();
                m.querySelectorAll('input[type="radio"]').forEach(r => {
                    if (!groups.has(r.name)) {
                        groups.add(r.name);
                        r.checked = true;
                        ['change','input','click'].forEach(ev =>
                            r.dispatchEvent(new Event(ev, {bubbles: true})));
                    }
                });
                const btn = document.querySelector('#submit-an-survey');
                if (btn) btn.disabled = false;
            }""")
            await self.page.wait_for_timeout(random.randint(800, 1500))
            try:
                await self.page.locator("#submit-an-survey").click(timeout=8_000)
                logger.info("  ✅ คลิก 'ส่งแบบสอบถาม' — รอ confirm popup")
            except Exception:
                pass
            await self.page.wait_for_timeout(2_000)

            # หลัง click ส่งแบบสอบถาม จะมี popup ยืนยัน — กดปุ่ม "ยืนยันการส่งแบบสอบถาม"
            try:
                confirm_btn = self.page.get_by_text("ยืนยันการส่งแบบสอบถาม", exact=False).first
                await confirm_btn.click(timeout=8_000)
                logger.info("  ✅ คลิก 'ยืนยันการส่งแบบสอบถาม'")
            except Exception as e:
                logger.warning(f"  no confirm popup: {e}")
                # fallback — auto-accept native dialog (ถ้าเป็น browser confirm())
                pass
            await self.page.wait_for_timeout(5_000)

        # 3. POST cert API (3 attempts only — ถ้ายังไม่ออกให้ background retry)
        cert_dt = None
        for attempt in range(3):
            cert_gen = await self.page.evaluate(f"""async () => {{
                try {{
                    const r = await fetch('/api/site/enroll/{enroll_id}/certificate', {{
                        method: 'POST', credentials: 'include',
                        headers: {{
                            'Content-Type':'application/json',
                            'X-Requested-With':'XMLHttpRequest',
                        }},
                        body: JSON.stringify({{lang:'th'}}),
                    }});
                    const t = await r.text();
                    try {{ return JSON.parse(t); }} catch (e) {{ return null; }}
                }} catch (e) {{ return null; }}
            }}""")
            cert_dt = (cert_gen or {}).get("certificate_datetime")
            logger.info(f"  cert try {attempt+1}/3 → certificate_datetime={cert_dt}")
            if cert_dt:
                break
            await self.page.wait_for_timeout(2_500)
        if not cert_dt:
            logger.warning(f"  cert ยังไม่ออก — จะให้ background retry ลองใหม่ทุก 15 นาที")
            return None

        # ดาวน์โหลด PDF ผ่าน JS fetch (คืนเป็น base64)
        cert_api = f"/api/site/enroll/{enroll_id}/certificate/th"
        try:
            b64 = await self.page.evaluate(f"""async () => {{
                const xsrf = document.cookie.split(';').map(c=>c.trim().split('=')).find(([k])=>k==='XSRF-TOKEN');
                const r = await fetch('{cert_api}', {{
                    method: 'GET',
                    headers: {{
                        'X-Requested-With': 'XMLHttpRequest',
                        'X-XSRF-TOKEN': xsrf ? decodeURIComponent(xsrf[1]) : '',
                    }},
                    credentials: 'include',
                }});
                if (!r.ok) return null;
                const buf = await r.arrayBuffer();
                const bytes = new Uint8Array(buf);
                let bin = '';
                bytes.forEach(b => bin += String.fromCharCode(b));
                return btoa(bin);
            }}""")

            if b64:
                import base64
                data = base64.b64decode(b64)
                if not data.startswith(b"%PDF"):
                    logger.warning(f"cert response ไม่ใช่ PDF (head={data[:20]!r}) — course ยังไม่ผ่าน")
                    return None
                pdf_path.write_bytes(data)
                logger.info(f"✅ cert saved: {pdf_path} ({pdf_path.stat().st_size:,} bytes)")
                return str(pdf_path)
        except Exception as e:
            logger.warning(f"cert fetch error: {e}")

        logger.warning("cert download failed — อาจยังไม่ผ่านเกณฑ์")
        return None

    async def watch_course(
        self,
        course_id: str,
        on_log: Optional[LogFn] = None,
        cert_dir: Optional[Path] = None,
    ) -> Optional[str]:
        """ดูคลิปทุก lesson + ทำ quiz + โหลด cert
        คืน path ของ PDF cert (None ถ้าโหลดไม่ได้)"""
        log = on_log or (lambda *a, **k: asyncio.sleep(0))
        url = SET_COURSE_URL.format(id=course_id)

        await log("sys", f"เปิดหลักสูตร {course_id}", None)
        await self.page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await self.page.wait_for_timeout(1500)
        await self._dismiss_popups()
        await self._shot(f"watch_{course_id}_01_landing")

        title = await self._course_title()
        if title:
            await log("sys", f"หลักสูตร: {title}", None)

        # คลิกเข้า player ถ้าหน้า landing แยก
        await self._enter_course()
        await self._shot(f"watch_{course_id}_02_entered")

        lessons = await self._collect_lessons()
        total = max(len(lessons), 1)
        await log("sys", f"เจอ {len(lessons)} บทเรียน", None)

        for i, lesson in enumerate(lessons, start=1):
            progress = str(int((i - 1) / total * 85))
            name = (lesson.get("text") or f"บทที่ {i}")[:50]
            await log("play", f"ดู {i}/{total}: {name}", progress)
            try:
                await self._open_lesson(lesson, i)
                await self._play_until_end()
            except Exception as e:
                logger.warning(f"lesson {i} failed: {e}")
                await self._shot(f"watch_{course_id}_lesson_{i}_failed")
                await log("err", f"บทที่ {i} ติด: {str(e)[:120]}", progress)

        # quiz
        await log("sys", "ทำแบบทดสอบ", "88")
        try:
            score = await self._do_quiz()
            await log("ok", f"ทำแบบทดสอบเสร็จ {score or ''}".strip(), "92")
        except Exception as e:
            await self._shot(f"watch_{course_id}_quiz_failed")
            await log("err", f"แบบทดสอบติด: {str(e)[:120]}", "92")

        # cert
        cert_path: Optional[str] = None
        if cert_dir is not None:
            try:
                cert_path = await self._download_cert(course_id, cert_dir)
                if cert_path:
                    await log("done", "ดาวน์โหลดวุฒิบัตรเสร็จ", "100")
                else:
                    await log("warn", "ดูจบ แต่ไม่เจอปุ่มดาวน์โหลดวุฒิบัตร", "100")
            except Exception as e:
                await self._shot(f"watch_{course_id}_cert_failed")
                await log("err", f"ดาวน์โหลด cert ติด: {str(e)[:120]}", "100")
        return cert_path

    async def _course_title(self) -> Optional[str]:
        try:
            return await self.page.evaluate("""() => {
                const h = document.querySelector('h1, h2, .course-title, [class*="course-name"], [class*="course-title"]');
                return h ? (h.innerText || '').trim().slice(0, 120) : null;
            }""")
        except Exception:
            return None

    async def _enter_course(self) -> None:
        """คลิกปุ่มเริ่มเรียน/ดูต่อ ถ้ามี — เพื่อเข้าหน้า player"""
        enter_selectors = [
            '.btn-trigger-enroll',                          # selector จริงบน SET
            'a:has-text("ดูต่อ")', 'button:has-text("ดูต่อ")',
            'a:has-text("เรียนต่อ")', 'button:has-text("เรียนต่อ")',
            'a:has-text("เริ่มเรียน")', 'button:has-text("เริ่มเรียน")',
            'a:has-text("เข้าเรียน")', 'button:has-text("เข้าเรียน")',
            'a.btn-primary:visible',
        ]
        for sel in enter_selectors:
            try:
                loc = self.page.locator(sel)
                if await loc.count() > 0 and await loc.first.is_visible(timeout=500):
                    await loc.first.click()
                    break
            except Exception:
                continue
        else:
            return  # ไม่เจอปุ่มเลย — อาจอยู่ใน player แล้ว

        # bug #2: รอ $.confirm popup แล้วกด "ตกลง"
        try:
            confirm_ok = self.page.locator('.jconfirm-buttons button:has-text("ตกลง")')
            await confirm_ok.wait_for(state="visible", timeout=3_000)
            await confirm_ok.click()
            logger.info("✅ กด ตกลง ใน $.confirm modal")
        except Exception:
            pass  # ไม่มี modal → click ทำ navigation ตรง

        # bug #3: ใช้ domcontentloaded เพราะ SET มี GA/tracking scripts ที่ block networkidle
        await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
        await self.page.wait_for_timeout(1500)

        # bug #4: guard ถ้า 401 kick เราออกจาก SET
        if "elearning.set.or.th" not in self.page.url:
            raise RuntimeError(
                f"ถูก redirect ออกจาก SET หลังกด enroll — session อาจ invalid (URL: {self.page.url})"
            )

    async def _collect_lessons(self) -> List[Dict]:
        """เก็บ lesson list บนหน้า player — return [{text, href, idx}]
        ลอง selector หลายแบบ; ถ้าไม่เจอ list ให้ assume single-video และคืน [{idx:0}]"""
        candidates = [
            'a[href*="/topics/"]',          # SET e-Learning: /enroll/{id}/topics/{tid}
            'a[href*="lesson"]', 'a[href*="episode"]',
            '.lesson-item', '.episode-item', '.chapter-item',
            '[class*="lesson"]', '[class*="episode"]', '[class*="chapter"]',
            'ul.playlist > li', '.video-list li', '.list-group .list-group-item',
        ]
        for sel in candidates:
            try:
                items = await self.page.evaluate(f"""(sel) => {{
                    const els = Array.from(document.querySelectorAll(sel));
                    return els.map((el, i) => ({{
                        idx: i,
                        text: (el.innerText || '').trim().slice(0, 160),
                        href: el.href || el.querySelector('a')?.href || null,
                        cls: (el.className?.toString() || '').slice(0, 120),
                        sel: sel,
                    }})).filter(x => x.text || x.href);
                }}""", sel)
                if items and len(items) >= 1:
                    # filter duplicate text
                    seen, uniq = set(), []
                    for it in items:
                        key = it["text"][:80] or it["href"]
                        if key in seen:
                            continue
                        seen.add(key)
                        uniq.append(it)
                    if len(uniq) >= 1:
                        logger.info(f"📚 ใช้ lesson selector: {sel} ({len(uniq)} items)")
                        return uniq
            except Exception:
                continue
        logger.info("📚 หา lesson list ไม่เจอ — assume single-video")
        return [{"idx": 0, "text": "video", "sel": "single"}]

    async def _open_lesson(self, lesson: Dict, n: int) -> None:
        """คลิกเปิดบทเรียนตาม dict ที่ _collect_lessons คืนมา"""
        if lesson.get("sel") == "single":
            # หน้าเดิม ไม่ต้องคลิกอะไร
            return
        # ถ้ามี href — goto ตรงเลย
        href = lesson.get("href")
        if href:
            await self.page.goto(href, wait_until="domcontentloaded", timeout=30_000)
            await self.page.wait_for_timeout(1000)
            return
        # ใช้ selector ตำแหน่ง index
        sel = lesson.get("sel")
        if sel:
            try:
                await self.page.locator(sel).nth(lesson["idx"]).click(timeout=5_000)
                await self.page.wait_for_timeout(1500)
            except Exception as e:
                logger.warning(f"คลิก lesson {n} ไม่ได้: {e}")

    async def _play_until_end(self) -> None:
        """เร่ง mute play แล้วรอจน video.ended === true"""
        # รอ <video> โผล่ — รอนานขึ้นเพราะ SET player โหลดช้า
        try:
            await self.page.wait_for_selector("video", timeout=30_000)
        except Exception:
            # ลอง iframe ทุก frame ที่มี src (ไม่ใช่ tracking iframe)
            iframes = await self.page.query_selector_all("iframe")
            for iframe in iframes:
                src = await iframe.get_attribute("src") or ""
                if not src or "about:blank" in src or "sharethis" in src or "_hj" in src:
                    continue
                logger.info(f"ตรวจพบ iframe: {src[:80]}")
                frame = await iframe.content_frame()
                if frame:
                    try:
                        await frame.wait_for_selector("video", timeout=10_000)
                        await self._play_in_frame(frame)
                        return
                    except Exception:
                        continue
            # ไม่มี video เลย — อาจเป็น infographic/slide → skip ได้
            logger.info("ไม่พบ <video> บนหน้านี้ (อาจเป็น infographic) — ข้ามไป")
            return

        await self.page.evaluate(f"""() => {{
            const v = document.querySelector('video');
            if (!v) return;
            v.muted = true;
            v.playbackRate = {VIDEO_SPEED};
            const p = v.play();
            if (p && p.catch) p.catch(() => {{}});
        }}""")

        # poll จน ended — มี cap กันหลุด
        try:
            await self.page.wait_for_function(
                """() => {
                    const v = document.querySelector('video');
                    return !v || v.ended || (v.duration > 0 && v.currentTime >= v.duration - 0.5);
                }""",
                timeout=WATCH_TIMEOUT_SEC * 1000,
            )
        except Exception:
            logger.warning("watch timeout — ข้ามไป lesson ถัดไป")

        # บางหลักสูตรต้องกด "ถัดไป" หลังคลิปจบ
        next_btn = self.page.locator(
            'button:has-text("ถัดไป"), button:has-text("Next"), '
            'a:has-text("ถัดไป"), a:has-text("Next")'
        )
        if await next_btn.count() > 0:
            try:
                await next_btn.first.click(timeout=2_000)
                await self.page.wait_for_timeout(800)
            except Exception:
                pass

    async def _play_in_frame(self, frame) -> None:
        await frame.evaluate(f"""() => {{
            const v = document.querySelector('video');
            if (!v) return;
            v.muted = true;
            v.playbackRate = {VIDEO_SPEED};
            const p = v.play();
            if (p && p.catch) p.catch(() => {{}});
        }}""")
        try:
            await frame.wait_for_function(
                """() => {
                    const v = document.querySelector('video');
                    return !v || v.ended || (v.duration > 0 && v.currentTime >= v.duration - 0.5);
                }""",
                timeout=WATCH_TIMEOUT_SEC * 1000,
            )
        except Exception:
            logger.warning("frame watch timeout")

    async def _do_quiz(self) -> Optional[str]:
        """กด quiz → ตอบข้อแรกทุกข้อ → submit; คืน score string ถ้าจับได้"""
        quiz_btn = self.page.locator(
            'a:has-text("ทำแบบทดสอบ"), button:has-text("ทำแบบทดสอบ"), '
            'a:has-text("แบบทดสอบ"), button:has-text("แบบทดสอบ"), '
            'a:has-text("Quiz"), button:has-text("Quiz")'
        )
        if await quiz_btn.count() > 0 and await quiz_btn.first.is_visible(timeout=1_000):
            await quiz_btn.first.click()
            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await self.page.wait_for_timeout(1500)

        # เลือกตัวเลือกแรกของทุกข้อ
        await self.page.evaluate("""() => {
            const groups = new Set();
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                if (r.name && !groups.has(r.name)) {
                    groups.add(r.name);
                    r.click();
                }
            });
        }""")
        await self.page.wait_for_timeout(500)

        submit = self.page.locator(
            'button:has-text("ส่งคำตอบ"), button:has-text("ส่ง"), '
            'button:has-text("Submit"), button[type="submit"]'
        )
        if await submit.count() > 0 and await submit.first.is_visible(timeout=1_000):
            await submit.first.click()
            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await self.page.wait_for_timeout(1500)

        # ดู score ที่หน้า result
        try:
            return await self.page.evaluate("""() => {
                const m = document.body.innerText.match(/(\\d+\\s*\\/\\s*\\d+|\\d+%|คะแนน[^\\n]{0,30})/);
                return m ? m[0].trim().slice(0, 40) : null;
            }""")
        except Exception:
            return None

    async def _download_cert(self, course_id: str, cert_dir: Path) -> Optional[str]:
        cert_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = cert_dir / f"cert_{course_id}.pdf"

        dl_btn = self.page.locator(
            'a:has-text("ดาวน์โหลดวุฒิบัตร"), button:has-text("ดาวน์โหลดวุฒิบัตร"), '
            'a:has-text("วุฒิบัตร"), a:has-text("ดาวน์โหลด"), '
            'a:has-text("Download"), button:has-text("Download")'
        )
        if await dl_btn.count() == 0:
            return None

        try:
            async with self.page.expect_download(timeout=30_000) as dl_info:
                await dl_btn.first.click()
            download = await dl_info.value
            await download.save_as(str(pdf_path))
            return str(pdf_path)
        except Exception as e:
            logger.warning(f"download cert failed: {e}")
            return None

    async def close(self) -> None:
        if DEBUG:
            # debug mode — ค้างไว้ 30 วิ ให้เห็น browser
            try:
                await self.page.wait_for_timeout(30_000)
            except Exception:
                pass
        if self.browser:
            await self.browser.close()
        if self.pw:
            await self.pw.stop()
