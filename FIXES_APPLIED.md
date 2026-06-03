# Fixes Applied — 2026-05-21

แก้ตาม [DEBUG_REPORT.md](DEBUG_REPORT.md) — รวม **20 bugs**

---

## 🔴 P0 — Critical (Money / Data Integrity)

| Bug | ไฟล์ | สิ่งที่แก้ |
|---|---|---|
| **#1** Double-dispatch | [`app/api/jobs.py`](app/api/jobs.py) | ลบ `run_automation.delay()` ออกจาก `create_job` — เหลือเฉพาะใน `verify_payment` |
| **#2** Worker ไม่เช็ค status/payment | [`app/worker/tasks.py`](app/worker/tasks.py) | เพิ่ม guard: skip ถ้า status ไม่ใช่ pending/queued, fail ถ้า payment.verified=False |
| **#3** `log_job` ใช้ Redis singleton ข้าม loop | [`app/utils/job_logger.py`](app/utils/job_logger.py) + [`tasks.py`](app/worker/tasks.py) | เพิ่ม `redis=` keyword arg — worker ส่ง client ของตัวเอง |
| **#4** Blocking sync ใน async endpoint | [`app/api/jobs.py`](app/api/jobs.py) | wrap `celery.inspect().ping()` ใน `run_in_executor` |
| **#9** total_price/total_hours ไม่ validate | [`app/schemas/job.py`](app/schemas/job.py) | เพิ่ม validators เช็คตัวเลข + min/max + dedupe courses |

## 🟡 P1 — Security / Stability

| Bug | ไฟล์ | สิ่งที่แก้ |
|---|---|---|
| **#5** Slip replay (reference None) | [`app/api/payments.py`](app/api/payments.py) | reject ทันทีถ้าอ่าน reference ไม่ได้ |
| **#7** Default secrets dangerous | [`app/config.py`](app/config.py) | เพิ่ม `IS_PRODUCTION` flag — raise ถ้า secret_key/admin_password เป็น default |
| **#8** CORS `["*"]` | [`app/main.py`](app/main.py) + [`config.py`](app/config.py) | เพิ่ม `CORS_ORIGINS` setting + whitelist |
| **#12** Survey submit ซ้ำ | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | เช็ค `survey_datetime` ก่อนทำ |
| **#13** `_filter_incomplete` ignore errors | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | ข้ามคอร์สที่ batch fail แทนเดา not_enrolled |
| **#14** `/tmp/` ไม่มีบน Windows | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | ใช้ `tempfile.gettempdir()` + atomic write |
| **#16** `verified-by-admin` truncate | [`app/api/admin.py`](app/api/admin.py) | เปลี่ยนเป็น `"admin"` (5 chars) + status guard |
| **#22** Redis TTL 30 นาทีสั้นไป | [`app/api/jobs.py`](app/api/jobs.py) + [`payments.py`](app/api/payments.py) | 30 นาที → 2 ชั่วโมง + extend on verify |
| **#26** Pre-test ตอบ option 0 ทุกข้อ | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | random index แทน (กัน SET detect pattern) |
| **#28** Admin force-verify ไม่เช็ค status | [`app/api/admin.py`](app/api/admin.py) | เพิ่ม guard เหมือน verify_payment |
| **#29** `rsplit("/")` ไม่จับ Windows path | [`app/utils/slipok.py`](app/utils/slipok.py) | ใช้ `Path(slip_path).name` |
| **#30** ขาด `channel="chrome"` | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | เพิ่มกลับ + fallback ถ้า chrome ไม่ install |
| **#31** Escape key รบกวน Angular | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | `_dismiss_popups(allow_escape=False)` default — login page ใช้ True |
| **#32** Duplicate `wait_for_selector` | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | ลบทิ้ง 1 รอบ |
| **#33** Hours parse ผิด (hr + min) | [`app/worker/dsl_client.py`](app/worker/dsl_client.py) | sum hr + min/60 แทน else-if |
| **#34** Course duplicate | [`app/schemas/job.py`](app/schemas/job.py) | dedupe + cap 50 |
| **#15** Bundle PDF silent skip | [`app/api/jobs.py`](app/api/jobs.py) | เพิ่ม `X-Merged-Count` + `X-Missing-Count` headers |
| **#39** JWT ไม่มี iat/jti | [`app/utils/security.py`](app/utils/security.py) | เพิ่ม `iat`, `nbf`, `jti` |
| **#41** Promptpay account format | [`app/api/payments.py`](app/api/payments.py) | validate 10/13/15 digits ก่อนสร้าง QR |

---

## 📋 ไฟล์ที่แก้ทั้งหมด

```
app/api/admin.py
app/api/jobs.py
app/api/payments.py
app/config.py
app/main.py
app/schemas/job.py
app/utils/job_logger.py
app/utils/security.py
app/utils/slipok.py
app/worker/dsl_client.py
app/worker/tasks.py
.env.example
```

ทั้ง 12 ไฟล์ผ่าน `ast.parse` syntax check ✅

---

## ⚠️ Round 2: bugs ที่เหลือ — แก้ครบแล้ว ✅

| Bug | ไฟล์ | สิ่งที่แก้ |
|---|---|---|
| **#6** Auth ownership | [`models/job.py`](app/models/job.py), [`api/auth.py`](app/api/auth.py), [`api/jobs.py`](app/api/jobs.py), [`api/ws.py`](app/api/ws.py), migration [`c8f4a3d92e10`](alembic/versions/c8f4a3d92e10_add_user_id_to_jobs.py) | เพิ่ม `Job.user_id` (nullable, backward-compat) + `get_optional_user` + `_check_ownership` + `GET /jobs/` list-my-jobs + WS token auth |
| **#9 deep** Server-side price | [`api/courses.py`](app/api/courses.py), [`api/jobs.py`](app/api/jobs.py) | `/courses/fetch` cache hours map ใน Redis (TTL 1 ชม) → `create_job` ตรวจ total_price จาก cache ±5% tolerance |
| **#20** Rate limit | [`main.py`](app/main.py), [`api/courses.py`](app/api/courses.py), [`requirements.txt`](requirements.txt) | เพิ่ม **slowapi** + Redis backend — `/courses/fetch` limit 3/นาที, 20/ชม. ต่อ IP |
| **#21** Cleanup uploads | [`worker/celery_app.py`](app/worker/celery_app.py), [`worker/tasks.py`](app/worker/tasks.py) | Celery beat `cleanup_old_uploads` ตี 3 ทุกวัน — ลบ slip + cert dir ของ job เก่ากว่า 30 วัน |
| **#23** Cache race | [`worker/dsl_client.py`](app/worker/dsl_client.py) | Redis hash `dsl:answer_cache` เป็น primary (atomic HSET) + file เป็น fallback ด้วย PID-suffix temp + atomic rename |
| **#25** Cert retry | [`worker/celery_app.py`](app/worker/celery_app.py), [`worker/tasks.py`](app/worker/tasks.py) | Celery beat `retry_pending_certs` ทุก 15 นาที — หา cert ที่ pdf_path=null + job done ภายใน 24 ชม. → relogin + retry download (limit 5/รอบ) |

### Dependencies ใหม่
```
slowapi==0.1.9    # rate limiting
pypdf==5.0.1      # PDF merge (เคยใช้แต่ไม่อยู่ใน requirements.txt)
```

### Migration ใหม่
```bash
alembic upgrade head   # apply c8f4a3d92e10_add_user_id_to_jobs
```

### Celery Beat — ต้อง start เพิ่ม
```bash
# worker (เหมือนเดิม)
celery -A app.worker.celery_app.celery worker --loglevel=info

# beat scheduler (เพิ่มใหม่ — รัน process แยก)
celery -A app.worker.celery_app.celery beat --loglevel=info
```

---

## 🚀 Next Steps — Deployment Checklist

### 1. อัปเดต dependencies
```bash
pip install -r requirements.txt
playwright install chrome   # ถ้าใช้ system Chrome
```

### 2. Run migration
```bash
alembic upgrade head
# จะ apply c8f4a3d92e10 → เพิ่ม column jobs.user_id (nullable)
```

### 3. ตั้ง `.env` ตาม `.env.example`
ค่าจำเป็น:
- `SECRET_KEY` — random ≥32 chars (encrypt + JWT)
- `ADMIN_PASSWORD` — ≥12 chars
- `CORS_ORIGINS` — comma-separated allowed origins
- `EXPECTED_ACCOUNT` — เลข PromptPay (10/13/15 หลัก)
- `IS_PRODUCTION=true` → จะ raise ถ้า default secrets ยังใช้อยู่

### 4. Start services
```bash
# API
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Worker (เหมือนเดิม)
celery -A app.worker.celery_app.celery worker --loglevel=info

# Beat scheduler (ใหม่ — รัน process แยก)
celery -A app.worker.celery_app.celery beat --loglevel=info
```

### 5. Smoke test
- [ ] `POST /courses/fetch` → กลับ courses + cache hours ใน Redis
- [ ] `POST /jobs/` → 422 ถ้า `total_price` ต่ำกว่า cached calculation
- [ ] `POST /jobs/` (no auth) → job.user_id=null, anyone with UUID เข้าได้
- [ ] `POST /jobs/` (with JWT) → job.user_id ตรงกับ user → คนอื่นเข้าไม่ได้ (403)
- [ ] `POST /payments/{id}/verify` → dispatch worker เพียงครั้งเดียว
- [ ] `WebSocket /ws/jobs/{id}?token=<jwt>` → auth check ผ่าน
- [ ] `GET /jobs/` (with JWT) → คืน list jobs ของ user เท่านั้น
- [ ] Spam `/courses/fetch` 4 ครั้ง/นาที → 429 Too Many Requests
- [ ] Celery beat — เช็ค log ทุก 15 นาทีว่า `retry_pending_certs` รันแล้ว
- [ ] รอ 30 วัน หรือ trigger `cleanup_old_uploads` manually → uploads/ เบาลง

---

## 📊 รวมสถิติการแก้

- **Round 1:** 20 bugs (P0/P1 immediate fixes)
- **Round 2:** 6 bugs (auth + price verify + rate limit + cleanup + cache + cert retry)
- **รวม:** 26 bugs ใน 17 ไฟล์ + 1 migration ใหม่
- **ผ่าน syntax check ทุกไฟล์** ✅
