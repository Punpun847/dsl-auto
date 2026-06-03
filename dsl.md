# DSL Automation — Index

> **AI ที่เข้ามาใหม่:** อ่านไฟล์นี้ก่อน → เข้าใจภาพรวม → เปิดไฟล์ย่อยตามที่ต้องการ
> **กฎ:** อัปเดตไฟล์ที่เกี่ยวข้อง + section Changelog ทุกครั้งที่มีการเปลี่ยนแปลง

อัปเดตล่าสุด: **2026-05-21**

---

## โปรเจกต์คืออะไร

ระบบ automation สำหรับ "เรียนคอร์ส SET e-Learning อัตโนมัติ" — user กรอก NID/PWD + เลือกคอร์ส + แนบสลิป → ระบบ login DSL portal → SSO ไป SET → ดูวิดีโอ → ทำแบบทดสอบ → ดาวน์โหลดวุฒิบัตร

**Stack:** FastAPI + Celery + Postgres + Redis + Playwright + Vanilla JSX frontend

---

## ไฟล์ย่อย

| ไฟล์ | เปิดเมื่อ |
|------|---------|
| [dsl-architecture.md](dsl-architecture.md) | อยากรู้ว่าไฟล์ไหนอยู่ตรงไหน, web flow ทำงานยังไง, DSLClient method อยู่ line ไหน, DB models มีอะไร, scripts ทำอะไร |
| [dsl-bugs.md](dsl-bugs.md) | อยากรู้ว่า bug ปัจจุบันคืออะไร, แก้ที่ไหน, สิ่งที่ debug แล้วค้นพบ, next steps ต้องทำอะไรต่อ |

---

## สถานะปัจจุบัน (quick summary)

**End-to-end pipeline ทำงานสมบูรณ์ ✅**

1. ✅ จ่ายเงิน → **SlipOK API** verify กับ ธปท. (primary) → fallback OCR
2. ✅ Login DSL + SSO ไป SET e-Learning (เช็ค celery worker active ก่อนรับงาน — กัน job ค้าง)
3. ✅ Mark topics 100% ผ่าน API ตรง
4. ✅ Pre-test 1 submit (ไม่ต้องผ่าน)
5. ✅ Post-test + Examination — **Gemini 2.5 Flash ตอบเป็น primary** + rotation fallback (max 3 attempts ลดเสี่ยง anti-cheat)
6. ✅ Survey best-effort + Cert generate + PDF download
7. ✅ Bundle PDF endpoint + Frontend banner + Live log + status realtime
8. ✅ **User auth system** (register/login/JWT) — เพื่อนเพิ่มในเวอร์ชัน master

**Known limitation:**
- 🟡 บาง course ระบบ SET ตั้ง `certificate=False` ถ้า submit แบบทดสอบเยอะเกินไป (anti-cheat)
- 🟡 Survey JS click บางครั้งไม่ trigger backend (acceptable เพราะ exam ≥70% มักไม่ require)

→ รายละเอียด API mapping + reverse-engineering ใน [`dsl-bugs.md`](dsl-bugs.md)

---

## Changelog

- **2026-05-15** — สร้างไฟล์ชุดนี้, รวม findings จาก debug session แรก: 401 issue, `$.confirm` popup, course_id numeric vs code, session race. แยกเป็น 3 ไฟล์ (index + architecture + bugs)
- **2026-05-15 (session 2)** — แก้ bug #2 (modal), #3 (networkidle→domcontentloaded ทั้งไฟล์), #4 (guard URL redirect), #6 (SET_COURSE_URL เพิ่ม /info). เพิ่ม `.btn-trigger-enroll` เป็น primary selector ใน `_enter_course`
- **2026-05-16 (session 3)** — debug 401 root cause: DSL ทำ SSO ผ่าน POST `api/v1/set-api/SetLogin` → JWT → Angular เปิด SET ใน new tab. `goto_set()` ใช้ `expect_page` แต่ไม่ yield event loop → tab เปิดแต่ Playwright จับไม่ทัน → guest session → 401. Fix: สร้าง `_sso_click_and_capture()` + `asyncio.sleep(5)` ใน context. `watch_course` ผ่านครบ flow แล้ว (SSO ✅, enroll ✅, quiz ✅). ยังค้าง: video player selector + SSO stability. Push ขึ้น GitHub (Punpun847/gyso-backend)
- **2026-05-17 (session 4)** — เปลี่ยนยุทธวิธีจาก "ดูวิดีโอ" → "API-based course completion": ใช้ `_filter_incomplete` (JS parallel fetch) + เพิ่ม `complete_course_via_api` ทำคอร์สผ่าน API ตรงๆ (no video playback). OCR สลิป — เพิ่ม pattern รองรับทุกธนาคารหลัก (KKP, KBank, SCB, BBL, KTB, BAY, GSB, Promptpay) + fallback search 4-digit tail ใน raw_text. Frontend ออกแบบใหม่: ปุ่มดาวน์โหลดวุฒิบัตรรวมเป็นปุ่มเดียว (pypdf merge) + status badges
- **2026-05-18 (session 5)** — แก้ปัญหาใหญ่ end-to-end:
  - **Topic mark complete API:** ค้นพบ pattern ผ่าน `capture_mark_complete.py` — POST `enroll2topic_stage` + `enroll/views` + `enroll2topic_duration` + `enroll2topic_status`
  - **Exam solver:** Hill-climbing strategy + smart early-freeze ลด submit 40% — capture จาก manual click พบว่า body ต้องมี `quiz2topic=` + match history score ด้วย `enroll2quiz_id` (กัน race)
  - **Type mapping:** ค้นพบว่า field ใน enroll response สลับชื่อกับ type จริง — `type=1`→`pre_test_percentage`, `type=4`→`post_test_percentage`, `type=3`→`exam_percentage`, `type=5`→`survey`
  - **Cert generate:** POST `/api/site/enroll/{eid}/certificate` ต้องส่ง JSON body `{"lang":"th"}` (ไม่ใช่ empty) เพื่อ trigger generate. เพิ่ม magic bytes check (`%PDF`) กัน save HTML
  - **Examination page:** มีปุ่ม "เริ่มแบบทดสอบ" ที่ต้องคลิกก่อน — เพิ่ม logic ใน `_submit_exam`. เปลี่ยน `has_exam` check จาก `enroll_data.exam` (ที่ empty สำหรับ fresh course) → ลองทำเสมอ
  - **Survey:** เพิ่ม `_submit_survey_on_summary` — expand accordion + เลือก radio + คลิก `#submit-an-survey` + คลิก "ยืนยันการส่งแบบสอบถาม" — JS-based fallback ทำงานในระดับ DOM แต่บางครั้งไม่ trigger backend (acceptable เพราะ survey ไม่ใช่ requirement หลัก)
  - **Anti-cheat awareness:** ระบบ SET ตั้ง `certificate=False` ถ้า submit เยอะเกินไป — pre-test เปลี่ยนเป็น 1 submit + solver stop ทันทีที่ผ่าน 70%
  - **Bug fixes:** job status ติด `running` (commit ก่อน redis cleanup), frontend setDone ผิด (filter `type=done` + `message includes "งานเสร็จสมบูรณ์"`), bank tolerant token (`นาคิน`,`ภัทร` แทน exact match)
  - **UI:** Banner ใหญ่ gradient mint + ปุ่ม pulse "ดาวน์โหลดวุฒิบัตรทั้งหมด (PDF เดียว)" + N/N count
  - **Verified working:** course 666 (3 topics, 100% all tests, cert.pdf 374KB), course 1291 (4 topics, exam 4/5=80%, cert.pdf 374KB)
- **2026-05-21 (session 9)** — Fix Gemini ReadTimeout: เพิ่ม timeout 30→90s ใน `llm_answer.py` (Gemini 2.5 Flash extended thinking บางครั้งใช้ >30s → ReadTimeout → fallback rotation → 0/10). Debug logging: log q_text 2 ข้อแรก + score page result count ก่อน/หลัง Gemini call. Verified: คอร์สวางแผนลดหนี้ (enroll_id=24530089) ผ่าน 7/10 = 70% หลัง fix
- **2026-05-20 (session 8)** — Fix course list + Celery event loop + Gemini retry:
  - **Celery "Event loop is closed":** หลัง task แรกจบ `asyncio.run()` ปิด loop → Playwright internal state ค้างใน process → task ที่สอง crash ทันที. Fix ใน `tasks.py`: เปลี่ยนจาก `asyncio.run()` → `loop = asyncio.new_event_loop()` + `set_event_loop(None)` หลังเสร็จ เพื่อ clear state ระหว่าง task
  - **Course filter (revert session 7 logic):** กลับมาแสดง catalog ที่ยังไม่ลงทะเบียนด้วย — user รายงานว่าหลักสูตรไม่ครบ. `_filter_incomplete` รวมทั้ง DSL-assigned (`status=not_started/in_progress`) + catalog (`status=not_enrolled`) ถ้ายังไม่มี cert. automation มี auto-enroll อยู่แล้วใน `complete_course_via_api` → คอร์ส catalog ทำงานต่อได้
  - **Gemini 503 retry:** เจอ exam ได้ 3/10 ทุกครั้งเพราะ Gemini ตอบ 503 "high demand" ตอน exam (pre-test ผ่าน 5/5 ปกติ). พอ LLM fail → fallback rotation = ทุกข้อตอบ option เดียวกัน = baseline ~25%. Fix ใน `llm_answer.py`: retry transient errors (429/500/502/503/504) ด้วย exp backoff 2s/5s/10s ก่อน return None
- **2026-05-20 (session 7)** — Auth merge + SlipOK + Gemini + UX:
  - **Merge auth จากเพื่อน:** ดึง register/login/JWT จาก `origin/master` (อยู่ใน subfolder `gyso-backend-main/`) มาผูกที่ root — เพิ่ม `app/api/auth.py`, `models/user.py`, `schemas/auth.py`, `frontend/auth.jsx`, migration `b3e9f1a2c4d5`. แก้ `main.py`, `security.py`, `config.py`, `models/__init__.py`, `requirements.txt`, `app.jsx`, `Nav`, HTML
  - **SlipOK API:** เปลี่ยนจาก OCR ดิบ → POST `https://api.slipok.com/api/line/apikey/{branch}` header `x-authorization: SLIPOK2LJP8CX` — verify กับ ธปท. แม่น 100% ปลอมไม่ได้ ฟรี 200/เดือน. ใหม่ใน `app/utils/slipok.py`. แก้ payments.py ให้ skip account/name/bank check ตอน SlipOK ผ่าน (SlipOK ผูกกับ branch ของเราในระบบ SlipOK แล้ว) — keep แค่ amount + dedupe ref + age
  - **Course filter:** ลบ catalog fallback ทิ้ง — return เฉพาะ DSL-assigned ที่ยังไม่ได้ cert. ถ้าว่าง → 404 "ไม่พบหลักสูตรที่ต้องทำ" (ไม่หลอกแสดง catalog 64+ ตัว)
  - **Gemini 2.5 Flash exam solver:** ค้นพบว่า score page ของ SET **ไม่แสดงเฉลย** → cache ไม่ build → rotation ผ่านยาก (~1.5%/attempt). แก้: attempt 0 ส่ง 5 ข้อให้ Gemini ตอบ (`gemini-2.5-flash:generateContent` + `responseMimeType: application/json`) — accuracy 80-95% verified ผ่านแล้ว 2 หลักสูตร. fallback rotation 2 รอบ. ลด MAX_ATTEMPTS 8→3 กัน anti-cheat
  - **Celery health check:** POST `/jobs/` เช็ค `celery.control.inspect(timeout=1.5).ping()` ก่อนรับงาน — ถ้าไม่มี worker → 503 "ระบบบอทกำลังปิดปรับปรุง" แทนปล่อย job ค้าง "running 0%"
  - **Frontend UX:** ลบ Hero mock cards, การ์ดข้อมูลมั่วๆ, link contact admin ที่ยังไม่มี; แก้ FAQ ให้ตรง (รองรับทุกหลักสูตร SET); payment page fetch `/payments/info` แสดงเลขบัญชี/ชื่อจริงจาก config; ปุ่ม submit lock หลังกด — เพิ่ม state `submitted` กัน double-click (เคยเจอ 3 jobs ติด); status card แสดง latest log msg เป็นสถานะปัจจุบัน + log box live + นับเวลาเล่นเป็นชั่วโมง
  - **Bug fixes:** duplicate slip ref → set `payment.reference` ถ้าไม่ซ้ำเท่านั้น + try/except commit (กัน 500); env `EXPECTED_RECIPIENT_NAME=ปุณณภพ โฆษิตสัจกุล`
  - **Verified working:** Macro Analysis (course 612) — Gemini ตอบ exam ได้ 80% ผ่าน, cert ออก 374KB
- **2026-05-19 (session 6)** — แก้ปัญหารวมและ exam solver:
  - **Redis "different event loop":** `get_redis()` cache instance ผูกกับ uvicorn loop, Celery fork มาใช้ loop ใหม่ → crash. Fix: สร้าง `aioredis.from_url()` ใหม่ทุก task ใน `tasks.py`
  - **Exam submit ช้า 2 นาที:** `await fetch('/questions2answer')` ไม่มี timeout → server throttle ทำให้ Playwright block. Fix: fire-and-forget + `AbortController` 20s ให้ fetch อื่น
  - **OCR amount อ่านผิด:** OCR ใช้ `จํานวน` (decomposed ํ+า) regex ใช้ `จำนวน` (precomposed ำ) → match ไม่ติด → fallback ไปเจอ noisy number. Fix: `text.replace("ํา", "ำ")` (NFC ไม่ช่วยเพราะ Thai combining chars ไม่ canonical-equiv)
  - **Bank check fail ทุกครั้ง:** สลิป mobile app แสดง logo ไม่มี text. Fix: เช็คเฉพาะเมื่อ OCR `_parse_bank` คืน non-null
  - **500 บน duplicate slip:** `payment.reference = ocr_reference` ถูก set ก่อน commit แม้รู้ว่า ref ซ้ำ → unique constraint ชน. Fix: ไม่ set ref ถ้า ref_is_dup, wrap commit ใน try/except
  - **Course filter (เห็น 64 ทั้งที่ไม่มี):** `_filter_incomplete` ใช้ `learning_percentage < 100` แต่ pct=100 แต่ cert ไม่ออก (anti-cheat) ก็ยังต้องทำ. Fix: ใช้ `certificate_datetime` เป็น primary check + two-pass filter (DSL-assigned ก่อน, catalog fallback ถ้าว่าง) + card HTML completion badge fast-path
  - **🌟 Exam solver ใหม่ (เปลี่ยนยุทธวิธีจาก hill-climbing → score-page caching):** ค้นพบว่า SET randomize ข้อสอบทุกครั้งที่สร้าง `enroll2quiz` ใหม่ (ยืนยันจาก score pattern `0→2` เปลี่ยน 1 answer = +2 ซึ่ง imposss ถ้าไม่ randomize) → hill-climbing ใช้ไม่ได้. ใหม่: submit → เปิด `/enroll/{eid}/exam/{e2q_id}/score` → parse DOM หา `.correct/.text-success` → cache `SHA1(question_text) → correct_value` ลง `/tmp/exam_answer_cache.json` (persistent) → attempt ถัดไปใช้ cache + rotate option สำหรับข้อที่ยังไม่รู้ → max 8 attempts. **Verified:** Macro Analysis (course 612) จาก 60% (hill-climbing เดิม 10 attempts ไม่ผ่าน) → 80% (solver ใหม่ผ่านในรอบเดียว)
