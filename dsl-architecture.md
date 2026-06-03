# DSL Architecture

อัปเดตล่าสุด: **2026-05-15**

---

## แผนที่ไฟล์

```
gyso-backend/
├── app/
│   ├── main.py                  ← FastAPI app, mount routers, serve frontend
│   ├── config.py                ← Settings (DATABASE_URL, REDIS_URL, ...)
│   ├── database.py              ← SQLAlchemy async session
│   ├── api/
│   │   ├── jobs.py              ← POST /jobs (create), GET /jobs/{id}, GET cert
│   │   ├── courses.py           ← POST /courses/fetch (DSLClient.fetch_courses)
│   │   ├── payments.py          ← จัดการสลิปการจ่ายเงิน
│   │   ├── admin.py             ← admin endpoints
│   │   └── ws.py                ← WebSocket stream progress logs
│   ├── worker/
│   │   ├── celery_app.py        ← Celery config
│   │   ├── tasks.py             ← run_automation Celery task (orchestrator)
│   │   └── dsl_client.py        ← ⭐ core automation logic
│   ├── models/
│   │   ├── job.py               ← Job model
│   │   ├── job_log.py           ← JobLog model
│   │   ├── certificate.py       ← Certificate model
│   │   └── payment.py           ← Payment model
│   ├── schemas/                 ← Pydantic schemas
│   └── utils/
│       ├── security.py          ← encrypt/decrypt password, hash_nid
│       ├── redis_client.py      ← Redis async client
│       └── job_logger.py        ← log_job() → JobLog + push WS
├── frontend/
│   ├── SLF Auto Volunteer.html  ← หน้าหลัก user (mount เป็น /)
│   ├── admin.html               ← admin panel (/admin-panel)
│   └── *.jsx                    ← app.jsx, sections.jsx, icons.jsx ฯลฯ
├── scripts/                     ← inspection/debug scripts (ไม่ใช่ production)
│   ├── inspect_course.py
│   ├── dump_courses.py
│   ├── find_enrolled.py
│   ├── debug_click_enroll.py
│   ├── debug_enroll_api.py
│   └── debug_enter_btn.py
├── alembic/                     ← migrations
├── uploads/                     ← slips, certs
├── venv/                        ← Python 3.9.6
└── .env                         ← DATABASE_URL, REDIS_URL, SECRET_KEY, ADMIN_PASSWORD, EXPECTED_ACCOUNT
```

---

## Web Flow (end-to-end)

```
[Frontend]
user กรอก NID/PWD → POST /courses/fetch
                 → DSLClient.fetch_courses() → รายการคอร์ส (id, code, title, hours)
user เลือก courses + แนบสลิป → POST /jobs/ (multipart)

[API: jobs.py]
→ บันทึก slip
→ สร้าง Job (status=pending) + Payment
→ encrypt NID/PWD → Redis (TTL 30 นาที, key: job:{id}:nid / pwd)
→ run_automation.delay(job_id)

[Celery Worker: tasks.py → _run()]
1. อ่าน NID/PWD จาก Redis + decrypt
2. DSLClient.start()
3. DSLClient.login(nid, pwd)
4. DSLClient.goto_set()             — SSO DSL → SET e-Learning
5. for course_id in job.courses:
     DSLClient.watch_course(course_id)
       ├─ _enter_course()           click "เข้าเรียน"/"ดูต่อ"
       ├─ _collect_lessons()        ดึง lesson list
       ├─ loop: _open_lesson()
                _play_until_end()   เล่นวิดีโอ
       ├─ _do_quiz()                ทำแบบทดสอบ
       └─ _download_cert()          save PDF → uploads/certs/{job_id}/
6. Job.status = done

[Frontend]
ดู progress real-time → WS /ws/{job_id}
ดาวน์โหลด cert → GET /jobs/{id}/certificate?course_id=...
```

---

## DSLClient — Methods Reference

ไฟล์: `app/worker/dsl_client.py`

**Constants (line 17–21):**
```python
DSL_BASE       = "https://wsa.dsl.studentloan.or.th"
LOGIN_URL      = f"{DSL_BASE}/#/rms/rms-login"
SET_BASE       = "https://elearning.set.or.th/SETStudentLoan"
SET_LIST_URL   = f"{SET_BASE}/list"
SET_COURSE_URL = f"{SET_BASE}/courses/{{id}}"   # ⚠️ ขาด /info (ดู dsl-bugs.md bug #6)
PRICE_PER_HOUR = ...
```

| Method | Line | หน้าที่ |
|--------|-----:|--------|
| `__init__` | 32 | สร้าง instance (รับ `headless`) |
| `start` | 54 | เปิด Playwright + browser context |
| `_dismiss_popups` | 61 | ปิด popup ประกาศ/cookies |
| `login` | 99 | login DSL portal |
| `fetch_courses` | 150 | ดึงรายการคอร์ส (paginated, GET only) |
| `_scrape_current_page` | 238 | scrape course cards — regex `/courses\/(\d+)/` → numeric id |
| `_goto_next_page` | 263 | คลิก pagination next |
| `goto_set` | 318 | SSO DSL → SET e-Learning |
| `watch_course` | 342 | orchestrator หลัก |
| `_course_title` | 406 | ดึง title คอร์ส |
| `_enter_course` | 415 | ⚠️ มีหลาย bugs (ดู dsl-bugs.md) |
| `_collect_lessons` | 435 | ⚠️ selectors ไม่ตรง SET จริง |
| `_open_lesson` | 473 | เปิด lesson ตัวที่ n |
| `_play_until_end` | 493 | เล่นวิดีโอ — ยังไม่ verify |
| `_play_in_frame` | 543 | เล่นวิดีโอใน iframe |
| `_do_quiz` | 563 | ทำแบบทดสอบ — ยังไม่ verify |
| `_download_cert` | 605 | ดาวน์โหลด PDF — ยังไม่ verify |
| `close` | 627 | ปิด browser |

---

## Database Models

| Model | ไฟล์ | Key fields |
|-------|------|------------|
| Job | `app/models/job.py` | id (UUID), nid_hash, courses (JSON list), status (enum), total_price, total_hours, completed_at |
| JobLog | `app/models/job_log.py` | job_id, type (sys/ok/play/err/done/warn), message, progress, timestamp |
| Certificate | `app/models/certificate.py` | job_id, course_id, pdf_path |
| Payment | `app/models/payment.py` | job_id, slip_path |

**JobStatus enum:** `pending → running → done / failed`

---

## Scripts (ใน `scripts/`)

ทุก script import `DSLClient` จาก `app.worker.dsl_client` — ใช้คลาสเดียวกับ production
รัน: `cd gyso-backend && venv/bin/python scripts/<name>.py <args>`

| Script | Args | Output | ใช้เมื่อ |
|--------|------|--------|---------|
| `dump_courses.py` | `NID PWD` | `/tmp/my_courses.json` | ดูรายการคอร์ส + หา numeric id (เช่น `WMD1037s` → `1942`) |
| `find_enrolled.py` | `NID PWD [MAX=5]` | `/tmp/find_enrolled.json` | หาคอร์สที่ enrolled (ปุ่ม "เข้าเรียน") vs ยังไม่ (ปุ่ม "ลงทะเบียน") |
| `inspect_course.py` | `NID PWD COURSE_ID` | `/tmp/course_<id>_*.png + .json` | inspect หน้า course detail + ลอง full flow |
| `debug_click_enroll.py` | `NID PWD COURSE_ID` | console + `/tmp/debug_after_enroll.png` | monitor DOM/network หลัง click enroll |
| `debug_enroll_api.py` | `NID PWD COURSE_ID` | console + `/tmp/debug_enroll_final.png` | capture POST `/enroll2learning` response body |
| `debug_enter_btn.py` | `NID PWD COURSE_ID` | console | dump DOM ละเอียดของปุ่ม "เข้าเรียน" |
