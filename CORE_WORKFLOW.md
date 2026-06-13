# Core Workflow — การทำงานหลักของ dsl-auto

ระบบทำ e-Learning กยศ. (SET Student Loan) อัตโนมัติ — รับงานจากลูกค้า → เข้าระบบ DSL/SET แทน
→ ทำคอร์ส + สอบ + ขอวุฒิบัตร ให้ครบ โดยไม่ต้องเล่นวิดีโอจริง

> อัปเดตล่าสุด: 2026-06-13

---

## 1. ภาพรวมสถาปัตยกรรม

```
ลูกค้า/แอดมิน ──▶ FastAPI (app/main.py) ──▶ Postgres (jobs, payments, certs)
                      │                          │
                      │ enqueue                  │ credential เข้ารหัส (TTL 2 ชม.)
                      ▼                          ▼
                 Redis (broker + cache) ◀──── Celery Worker
                      │                          │
                      │                          ▼
                 answer bank (เฉลย)      DSLClient (Playwright headless)
                                                 │
                                                 ▼
                                   DSL portal ──SSO──▶ SET e-Learning API
```

| ชั้น | เทคโนโลยี | ไฟล์หลัก |
|---|---|---|
| API / web | FastAPI + static HTML | `app/main.py`, `app/api/*` |
| งานเบื้องหลัง | Celery (broker = Redis) | `app/worker/celery_app.py`, `app/worker/tasks.py` |
| ออโตเมชัน | Playwright (Chromium headless) | `app/worker/dsl_client.py` |
| ฐานข้อมูล | Postgres (async SQLAlchemy) | `app/models/*` |
| cache / คิว / session | Redis | `app/utils/redis_client.py`, `answer_cache.py` |
| ตอบข้อสอบ | answer bank (cache) → LLM fallback | `app/utils/answer_cache.py`, `llm_answer.py` |

---

## 2. Lifecycle ของงาน (Job) แบบ end-to-end

### ขั้น A — สร้างงาน (API, ฝั่งเว็บ)
1. **ดึงคอร์ส** `POST /courses/fetch` ([courses.py](app/api/courses.py)) — login DSL ด้วย NID+รหัส
   ของ user → คืนคอร์สที่ยังไม่เสร็จ + จำนวนชั่วโมง → cache ผลใน Redis 1 ชม.
   (ราคา = ชั่วโมง × `PRICE_PER_HOUR` = 3 บาท)
2. **สร้างงาน** `POST /jobs/` ([jobs.py](app/api/jobs.py)):
   - ถ้า **FREE_MODE** เปิด → ไม่ต้องสลิป, `total_price=0`, payment auto-verified, `status=queued`
   - ถ้าปิด → ต้องแนบสลิป + verify ราคา server-side (เทียบกับ cache จาก `/courses/fetch`)
   - บันทึก `Job` + `Payment` ลง Postgres
   - เก็บ **NID + รหัสผ่านที่เข้ารหัส** ใน Redis (`job:{id}:nid` / `:pwd`, TTL 7200s)
   - ถ้าฟรี → `run_automation.delay(job_id)` (dispatch worker ทันที)
3. **(แอดมิน)** `POST /admin/panel/run-free` — สร้างงานฟรีเสมอ ผูกกับบัญชี admin
   (ดู [ADMIN_PANEL.md](ADMIN_PANEL.md))

> ฝั่งจ่ายเงิน: เมื่อ verify สลิปผ่าน (SlipOK) ใน [payments.py](app/api/payments.py) จึงค่อย
> dispatch `run_automation`

### ขั้น B — รันงาน (Celery worker)
หัวใจคือ `_run(job_id)` ใน [tasks.py](app/worker/tasks.py):

1. รันใน **fresh event loop** ทุก task (กัน state ของ Playwright ค้างข้ามงาน)
2. โหลด `Job` + guard:
   - ข้ามถ้า status ไม่ใช่ `pending`/`queued` (กันทำซ้ำ)
   - ต้องมี `Payment.verified=True` (กันบอทวิ่งฟรีโดยไม่ตั้งใจ)
3. ตั้ง `status=running` → ถอดรหัส NID/รหัสผ่านจาก Redis
4. เปิด `DSLClient` (Playwright) แล้ว:
   - `login()` → DSL portal
   - `goto_set()` → SSO เข้า SET e-Learning
   - วนทุกคอร์ส → `complete_course_via_api()` → สร้าง `Certificate` row ต่อคอร์ส
5. จบ → `status=done` + `completed_at`, log `"งานเสร็จสมบูรณ์ ✅"`, ลบ credential ใน Redis
6. error → `status=failed` + log ข้อความ; `finally` ปิด browser เสมอ

ทุก log เขียนผ่าน `log_job()` → ลง Postgres (`JobLog`) **และ** push เข้า Redis pub/sub
→ frontend เห็นความคืบหน้าสดผ่าน WebSocket `/ws/jobs/{id}`

### ขั้น C — ทำคอร์สผ่าน API (ไม่เล่นวิดีโอ)
`complete_course_via_api()` ใน [dsl_client.py](app/worker/dsl_client.py:657) — ยิง API ของ SET
ตรงๆ ผ่าน `page.evaluate` (ใช้ XSRF token จาก cookie):

| # | ขั้นตอน | API ของ SET |
|---|---|---|
| 1 | ดึง course info + `enroll_id` | `GET /api/site/groups/SETStudentLoan/courses/{id}` |
| 2 | enroll ถ้ายังไม่ลงทะเบียน | `POST /api/site/enroll2learning` |
| 3 | ดึง topics (แตก nested parent→leaf) | `GET /api/site/enroll/{enroll_id}` |
| 4 | **mark complete** ทุก topic | `enroll2topic_stage` → `enroll/views` → `enroll2topic_duration` (duration=0) → `enroll2topic_status` (status=1) |
| 4b | verify % เสร็จ | refetch `enroll/{id}` |
| 5–7 | **แบบทดสอบ** pre-test / post-test / exam | `_submit_exam()` — ทำเฉพาะที่คอร์สมีจริง (อ่านจาก course_data, ข้ามตัวที่ null กันเสียเวลา) |
| 7b | survey ในหน้า `/summary` | `_submit_survey_on_summary()` — ข้ามถ้าทำแล้ว (`survey_datetime`) |
| 8 | ขอ + ดาวน์โหลดวุฒิบัตร | `_request_and_download_cert()` → PDF ลง `uploads/certs/{job_id}/` |

> trick หลัก: SET mark topic ว่าดูจบด้วยการ POST `duration=0` + `status=1` — ไม่ต้องเล่นวิดีโอ

---

## 3. Engine ตอบข้อสอบ (`_submit_exam`)

อยู่ที่ [dsl_client.py:965](app/worker/dsl_client.py:965). กลยุทธ์ **cache-first** เพื่อไม่เสีย LLM cost:

1. เปิดหน้า exam → คลิก "เริ่มทำแบบทดสอบ" → poll หา `<input type=radio>` (สูงสุด 25s)
2. อ่านคำถาม (radio `name` = question id) + ตัวเลือก + `quiz_id`
3. **หาเฉลย** ตามลำดับ:
   - **Answer bank** (`answer_cache.load()`): hash คำถาม (SHA1 12 ตัว, ตัดเลขข้อนำหน้า +
     normalize whitespace กัน SET สลับลำดับ) → ดึงคำตอบที่เคยถูก
   - ถ้า cache ไม่ครบ → **LLM** (`llm_answer.py`: DeepSeek → Claude fallback) ถ้าเปิดใช้
   - submit → อ่าน score page → **บันทึกคำตอบที่ถูกกลับเข้า bank** (`answer_cache.save()`)
     ให้ attempt/งานถัดไปใช้ได้ฟรี
4. retry หลายครั้งจนผ่านเกณฑ์ (SET randomize ข้อต่อ attempt — แต่ hash เดิม จึง match cache ได้)

**Answer bank** ([answer_cache.py](app/utils/answer_cache.py)):
- เก็บใน Redis hash `dsl:answer_cache` (shared ทุก worker) + ไฟล์ backup
- `save()` ใช้ `HSET` เฉพาะ field ใหม่ (atomic, กัน worker อื่น clobber)
- ยิ่งทำงานมาก bank ยิ่งโต → พึ่ง LLM น้อยลง (สถานะปัจจุบัน: cache-only, ปิด LLM)

---

## 4. งานตามเวลา (Celery Beat)

ตั้งใน [celery_app.py](app/worker/celery_app.py):

| Task | ความถี่ | หน้าที่ |
|---|---|---|
| `retry_pending_certs` | ทุก 15 นาที | หา cert ที่ `pdf_path=null` + job done ใน 24 ชม. → ลองโหลดใหม่ (batch 5, ถ้า session ยังไม่หมดอายุ) |
| `cleanup_old_uploads` | ตี 3 ทุกวัน | ลบสลิป + cert dir ของงาน done/failed ที่เกิน 30 วัน |

---

## 5. โมเดลข้อมูล (Postgres)

| Model | ฟิลด์สำคัญ | หมายเหตุ |
|---|---|---|
| `User` | email, hashed_pwd, `is_admin`, is_active | JWT auth |
| `Job` | `user_id`, `nid_hash`, `courses[]`, `total_price/hours`, `status` | status: pending→queued→running→done/failed |
| `Payment` | `job_id`, `slip_path`, `verified`, amount | `slip_path="FREE"` เมื่อฟรี |
| `Certificate` | `job_id`, `course_id`, `pdf_path` | 1 row ต่อคอร์ส |
| `JobLog` | `job_id`, type, message, progress | สตรีมผ่าน WebSocket |

> NID ไม่เคยเก็บ raw — เก็บแค่ `nid_hash` (DB) + เข้ารหัสชั่วคราวใน Redis ระหว่างรันงาน
> (`security.py`); `nid_registry.json` ใช้ reverse hash → NID สำหรับ dashboard เท่านั้น

---

## 6. ความทนทาน (resilience) ที่ออกแบบไว้

- **fresh event loop + NullPool + redis client ใหม่ทุก task** — กัน "attached to a different loop"
  / connection ค้างข้ามงานใน Celery worker
- **idempotent guards** — ไม่รันงานที่ทำไปแล้ว, ไม่ทำ survey ซ้ำ (กัน anti-cheat ของ SET)
- **cache-first answers** — ไม่พึ่ง LLM, ตอบฟรีหลังสะสมเฉลยพอ
- **ข้ามแบบทดสอบที่คอร์สไม่มี** — ประหยัด ~33s/component ที่จะเสียไปกับ poll radio ที่ไม่มี
- **canonical question hash** — กัน SET สุ่มสลับลำดับข้อทำให้ cache miss
- **beat retry** — cert ที่โหลดพลาดถูกตามเก็บอัตโนมัติทุก 15 นาที

---

## 7. รันทั้งระบบ (local)

```bash
# 1. infra
docker-compose up -d postgres redis

# 2. API
PYTHONPATH=. python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# 3. worker (+ beat สำหรับ task ตามเวลา)
celery -A app.worker.celery_app.celery worker --pool=solo -l info
celery -A app.worker.celery_app.celery beat -l info
```

หน้าลูกค้า: `http://127.0.0.1:8001/` · หน้าแอดมิน: `/admin-panel`
