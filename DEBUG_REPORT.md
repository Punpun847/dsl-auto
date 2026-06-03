# GYSO Backend — Debug Report (จุดบอด/Blind Spots)

> วิเคราะห์เมื่อ 2026-05-21 หลังอ่านไฟล์ทั้งหมดในโปรเจกต์
> รวม 40+ bugs / weak points แยกตามความรุนแรง

---

## 🔴 CRITICAL — กระทบ Data Integrity / Money Flow

### BUG-1 — Double Dispatch: บอทวิ่งก่อนจ่ายเงิน

**ตำแหน่ง:** `app/api/jobs.py:94-95` + `app/api/payments.py:249-250`

```python
# jobs.py:94 — create_job() — dispatch ทันทีที่สร้าง job!
from app.worker.tasks import run_automation
run_automation.delay(str(job.id))
```

```python
# payments.py:249 — verify_payment() — dispatch อีกครั้งหลัง verify
from app.worker.tasks import run_automation
run_automation.delay(str(job.id))
```

**ผลที่เกิด:**

```
t=0   POST /jobs/        → Job(status=pending) + dispatch worker #1
t=2s  Worker #1 รับงาน    → ตั้ง running → login DSL → ทำคอร์ส → done → ลบ NID/PWD จาก Redis
t=30s POST /payments/{}/verify → ตั้ง status=queued → dispatch worker #2
t=32s Worker #2 รับงาน    → ตั้ง running → อ่าน Redis = empty → "ไม่พบ session" → failed
```

**ผลกระทบ:**
- บอทวิ่งทำคอร์สโดยที่ user ยังไม่จ่ายเงิน
- Status flip-flops `pending → running → done → queued → running → failed`
- User เห็น status สุดท้าย "failed" ทั้งที่ cert ถูกออกแล้ว
- ผู้ใช้ที่ตั้งใจเรียกใช้ `force-verify` (admin) จะวิ่งซ้ำเป็นรอบ 3

**Fix:**
```python
# jobs.py:93-95 — ลบ 3 บรรทัดนี้ออก
- # ส่งงานเข้า Celery queue
- from app.worker.tasks import run_automation
- run_automation.delay(str(job.id))
```

---

### BUG-2 — Worker ไม่เช็ค Job Status & Payment Verified

**ตำแหน่ง:** `app/worker/tasks.py:54-67`

```python
async with WorkerSession() as db:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        await redis.aclose()
        return

    job.status = JobStatus.running   # ← ไม่เช็ค status เดิม / ไม่เช็ค payment
    await db.commit()
```

ไม่มีการตรวจ:
1. `job.status` ปัจจุบัน — task ที่ 2 จะทับ `done` กลับเป็น `running`
2. `payment.verified` — บอทวิ่งโดยไม่สนใจว่าจ่ายเงินแล้วหรือยัง

**Fix:**
```python
# ตรวจ status + payment ก่อนเริ่ม
if job.status not in (JobStatus.pending, JobStatus.queued):
    logger_module.warning(f"job {job_id} status={job.status.value} — skip")
    return

payment_result = await db.execute(select(Payment).where(Payment.job_id == job_id))
payment = payment_result.scalar_one_or_none()
if not payment or not payment.verified:
    await log_job(db, job_id, "err", "งานนี้ยังไม่ได้ verify payment")
    job.status = JobStatus.failed
    await db.commit()
    return
```

---

### BUG-3 — `log_job()` ใช้ Redis Singleton ข้าม Event Loop

**ตำแหน่ง:** `app/utils/job_logger.py:32` + `app/utils/redis_client.py:7-14`

```python
# redis_client.py — global singleton
_pool: Optional[aioredis.Redis] = None

def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = aioredis.from_url(...)   # สร้างใน loop A
    return _pool                          # task ที่ 2 ได้ pool ของ loop A กลับ
```

```python
# tasks.py:50 — comment ระบุชัดว่ารู้ปัญหา
# สร้าง redis client ใหม่ใน event loop นี้ — กัน "attached to a different loop"
redis = aioredis.from_url(settings.redis_url, decode_responses=True)
```

```python
# tasks.py:73 — แต่ on_log → log_job → get_redis() (singleton เก่า!)
async def on_log(type, message, progress=None):
    await log_job(db, job_id, type, message, progress)

# job_logger.py:38
redis = get_redis()      # ← Pool ผูกกับ loop เก่า → RuntimeError
await redis.publish(...)
```

Changelog 2026-05-19 บอกว่า "Fix: สร้าง `aioredis.from_url()` ใหม่ทุก task" — แต่แก้แค่ใน `tasks.py` ลืม `log_job`

**Fix:** ส่ง redis client เข้าไปใน `log_job`:
```python
async def log_job(db, job_id, type, message, progress=None, *, redis=None):
    ...
    r = redis if redis is not None else get_redis()
    await r.publish(...)

# tasks.py
async def on_log(t, m, p=None):
    await log_job(db, job_id, t, m, p, redis=redis)
```

หรือใช้ context-aware:
```python
def get_redis() -> aioredis.Redis:
    # สร้างใหม่ทุกครั้ง ไม่ cache
    return aioredis.from_url(settings.redis_url, decode_responses=True)
```

---

### BUG-4 — Blocking Sync Call ใน Async Endpoint

**ตำแหน่ง:** `app/api/jobs.py:24-32`

```python
def _celery_worker_alive() -> bool:
    try:
        from app.worker.celery_app import celery
        replies = celery.control.inspect(timeout=1.5).ping()   # sync I/O!
        return bool(replies)
    except Exception:
        return False

@router.post("/")
async def create_job(...):
    if not _celery_worker_alive():   # ← Block FastAPI event loop 1.5s/request
```

`celery.control.inspect().ping()` ใช้ Kombu sync I/O → event loop ถูก freeze → ทุก request อื่นรอ

**Fix:**
```python
async def _celery_worker_alive() -> bool:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _sync_ping)

def _sync_ping() -> bool:
    try:
        from app.worker.celery_app import celery
        return bool(celery.control.inspect(timeout=1.5).ping())
    except Exception:
        return False
```

---

### BUG-5 — Slip Replay Attack (ภายในเวลา 30 นาที)

**ตำแหน่ง:** `app/api/payments.py:163-173` + DB constraint

```python
# unique constraint: payments.reference (มี index)
# แต่ถ้า OCR อ่าน reference เพี้ยน → ตรงไหนๆ ก็ผ่าน
if ocr_reference:
    with db.no_autoflush:
        dup_result = await db.execute(
            select(Payment).where(
                Payment.reference == ocr_reference,
                Payment.id != payment.id,
            )
        )
    if dup_result.scalar_one_or_none():
        errors.append("สลิปนี้เคยใช้กับ job อื่นแล้ว")
```

**ปัญหา:** ถ้า OCR อ่าน reference ออกมา `None` (เพราะภาพเบลอ) → ระบบไม่บันทึก reference → submit สลิปเดิมใหม่ → OCR ครั้งที่ 2 ออก `None` อีก → bypass dedup

นอกจากนั้น SlipOK fallback ไม่ได้ตรวจ unique reference ในระบบ:
```python
# payments.py:124 — SlipOK ผ่าน → ใช้ payload โดยไม่เช็คซ้ำ
slip = {
    "reference": sok["reference"],
    ...
}
```
SlipOK อาจ throttle ซ้ำเร็วเกินไป แต่ระบบยังพึ่ง unique constraint อย่างเดียว

**Fix:**
1. ถ้า reference อ่านไม่ได้ทั้ง OCR + SlipOK → reject (ไม่ accept)
2. เพิ่ม hash(slip_image_bytes) เป็น secondary dedup

---

## 🔴 CRITICAL — Security

### BUG-6 — ไม่มี Auth บน Job/Certificate Endpoints

**ตำแหน่ง:** `app/api/jobs.py:101-180`

```python
@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    # ใครก็เข้าได้ ถ้ารู้ UUID

@router.get("/{job_id}/certificate")
async def get_certificate(job_id: str, course_id: str, ...):
    # ดาวน์โหลด PDF ใคร็ได้
```

ทุก endpoint ใต้ `/jobs/*` ไม่มี `Depends(get_current_user)` — เจอใน WebSocket ด้วย:
```python
# ws.py:14
@router.websocket("/ws/jobs/{job_id}")
async def job_ws(websocket: WebSocket, job_id: str):
    # ไม่มี auth — sniff log ของคนอื่นได้ live
```

UUID v4 เดามายาก แต่ถ้า log/cache leak job_id ใครก็ผ่าน

**Fix:** เพิ่ม ownership check
```python
@router.get("/{job_id}")
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ตรวจว่า nid_hash ตรงกับ user
```

แต่ ปัญหาคือ — `Job` ไม่มี `user_id` foreign key! ระบบเลยตรวจ ownership ไม่ได้

**Fix ลึก:** เพิ่ม `Job.user_id` column + migration

---

### BUG-7 — Secrets Defaults ที่อันตราย

**ตำแหน่ง:** `app/config.py:7-9`

```python
secret_key: str = "change-this-to-a-random-secret-key"  # ← ใช้ encrypt NID/PWD!
admin_password: str = "admin1234"                        # ← admin panel
```

ถ้า `.env` ไม่ตั้ง:
- `SECRET_KEY` → AES-GCM key จะ derive จาก string คงที่ → ทุกคนที่ download code ถอดรหัสได้
- `JWT_SIGNING` → forge token ของใครก็ได้
- `ADMIN_PASSWORD` → bruteforce 4 หลักรอบเดียวผ่าน

ที่หนักกว่านั้น `.env.example` มีแค่ 4 keys → admin/slipok/gemini ทุกคนจะ leave default:
```bash
DATABASE_URL=...
REDIS_URL=...
SECRET_KEY=change-this-to-a-random-secret-key  # ← ตัวอย่างใช้ค่า default
UPLOAD_DIR=./uploads
```

**Fix:** บังคับ raise ถ้า default
```python
@validator("secret_key")
def check_secret(cls, v):
    if "change-this" in v.lower():
        raise ValueError("SECRET_KEY must be set in .env to a strong random value")
    return v
```

---

### BUG-8 — CORS `allow_origins=["*"]`

**ตำแหน่ง:** `app/main.py:13-17`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

ใครก็เรียก API จาก browser ที่อื่นได้ → ถ้า user login แล้ว → site อื่นยิง POST /jobs/ ผ่าน CSRF ได้ทันที (เพราะไม่มี CSRF token, JWT ส่งใน Authorization header แต่ wildcard CORS อนุญาตให้เว็บอื่นส่งได้)

**Fix:**
```python
allow_origins=[settings.frontend_origin],   # whitelist
allow_credentials=True,
```

---

### BUG-9 — `total_price` / `total_hours` Trust User Input

**ตำแหน่ง:** `app/schemas/job.py:11-13`

```python
class JobCreate(BaseModel):
    total_price: str    # ← ไม่ validate ว่าเป็นตัวเลข
    total_hours: str    # ← เหมือนกัน
```

User ส่ง `total_price=1` แทน `total_price=300` → จ่ายแค่ 1 บาท → SlipOK ยืนยัน 1 บาท → ผ่าน verify → บอททำ 100+ ชั่วโมงให้

`verify_payment` เทียบ:
```python
expected_amount = float(job.total_price)  # = 1.0
if abs(ocr_amount - expected_amount) > 0.5: errors.append(...)
```
ถ้า user จ่าย 1 บาท จริง ก็ผ่าน

**Fix:** Backend คำนวณราคาจากรายการ courses เอง:
```python
# courses.py แล้ว return raw hours
# jobs.py: คำนวณ total_price จาก server-side rate × DB-fetched hours
total_price = sum(c.hours for c in selected_courses) * PRICE_PER_HOUR
```

ตอนนี้ราคาเชื่อ client 100% → exploit ได้

---

### BUG-10 — NID/PWD Logged ใน DEBUG Mode

**ตำแหน่ง:** `app/worker/dsl_client.py:111-117`

```python
logger.info(f"⌨️  type NID ({len(nid)} chars)")
await self.page.type("#citizenFld", nid, delay=30)

logger.info(f"⌨️  type password ({len(pwd)} chars)")
await self.page.type("#passwordFld", pwd, delay=30)
```

แค่ length OK แต่ใน DEBUG mode `_shot()` ถ่ายภาพ full page — `screenshot path=/tmp/dsl_02_filled.png` จะมี password ที่ unmask อยู่ใน DOM (ถ้า input type ไม่ใช่ password — แต่ตรงนี้น่าจะใช้ type=password อยู่)

ยังมี exception logger ที่อาจ leak:
```python
except Exception as e:
    self.last_error = f"login exception: {e}"   # ← exception อาจมี stacktrace มี cred
```

---

### BUG-11 — Frontend Static Mount เปิด Source ทั้งหมด

**ตำแหน่ง:** `app/main.py:27`

```python
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
```

`StaticFiles` serve ทุกไฟล์ใน frontend/ รวมถึง `.jsx` source — anyone GET `/static/app.jsx`, `/static/auth.jsx` เห็น API endpoints + logic ทั้งหมด

ไม่ใช่ security issue ตรงๆ (เพราะ code ปกติ public อยู่แล้วใน browser) แต่ frontend ที่มี comment ภายในจะ leak

---

## 🟡 HIGH — Logic / Correctness

### BUG-12 — Survey ถูก Submit สองครั้ง

**ตำแหน่ง:** `dsl_client.py:643-651` + `dsl_client.py:1159-1209`

```python
# complete_course_via_api step 7b
await log("sys", "ทำแบบสอบถาม...", "90")
survey_ok = await self._submit_survey_on_summary(enroll_id)
```

จากนั้นใน `_request_and_download_cert`:
```python
# step 2
if modal_visible:
    # fill radio + click #submit-an-survey + ยืนยัน
```

`#surveyModal` ใน summary page อาจยังโผล่ขึ้นอีกครั้งหลังกด `.btn-download-certificate` → submit รอบ 2 → server อาจ reject → log warning + เสียเวลา

**Fix:** ตรวจ `survey_datetime` ก่อนทำ
```python
async def _ensure_survey_done(self, enroll_id):
    check = await self.page.evaluate(f"...survey_datetime")
    if check: return  # done already
    return await self._submit_survey_on_summary(enroll_id)
```

---

### BUG-13 — `_filter_incomplete` Silently Ignore API Errors

**ตำแหน่ง:** `dsl_client.py:294-297`

```python
try:
    results = await self.page.evaluate("""async (batch) => { ... }""", batch)
    for r in results:
        status_map[r["id"]] = r
except Exception as e:
    logger.warning(f"filter batch error: {e}")
    # ← ไม่มี handler — batch ที่ fail จะไม่มี entry ใน status_map
```

ถ้า batch fail → courses ใน batch นั้นไม่มี entry ใน `status_map` → fallback:
```python
for c in needs_api:
    s = status_map.get(str(c["id"]), {})   # = {} ถ้า batch fail
    cert = s.get("cert")  # = None
    enroll_id = s.get("enroll_id")  # = None
    if cert: ... # skip
    if enroll_id: ...
    else:
        c["status"] = "not_enrolled"   # ← เข้า branch นี้
    incomplete.append(c)
```

ผล: คอร์สที่ user เรียนจบแล้ว แต่ batch fail → ถูกแสดงเป็น "not_enrolled" → user เลือก → บอทพยายามทำซ้ำ → อาจ trigger anti-cheat

---

### BUG-14 — `/tmp/` ไม่มีบน Windows

**ตำแหน่ง:** `dsl_client.py:49, 675, 685` (และอีกหลายจุด)

```python
await self.page.screenshot(path=f"/tmp/dsl_{name}.png", full_page=True)
cache_file = "/tmp/exam_answer_cache.json"
with open("/tmp/exam_answer_cache.json", "w") as f:
```

User memory บอกว่า working dir = `D:\terminter01\gyso-backend-main` (Windows) → `/tmp/` map เป็น `C:\tmp\` (ถ้ามี) หรือ error

ถ้า run บน Windows native (ไม่ใช่ WSL):
- screenshots fail silently (try/except ครอบ)
- answer cache load = `{}` ทุกครั้ง — ไม่ persist ระหว่าง task
- _save_answer_cache log warning แต่ไม่ raise

**Fix:**
```python
import tempfile
CACHE_DIR = Path(tempfile.gettempdir()) / "gyso_dsl"
CACHE_DIR.mkdir(exist_ok=True)
cache_file = CACHE_DIR / "exam_answer_cache.json"
```

---

### BUG-15 — Bundle PDF Endpoint คืน Truncated PDF เงียบๆ

**ตำแหน่ง:** `app/api/jobs.py:131-164`

```python
for c in certs:
    if not c.pdf_path or not os.path.exists(c.pdf_path):
        continue   # ← skip silently
    try:
        reader = PdfReader(c.pdf_path)
        for page in reader.pages:
            writer.add_page(page)
        merged += 1
    except Exception:
        continue   # ← skip silently
```

ถ้า 5 cert จาก 10 ไฟล์เสีย/หาย → user ได้ PDF 5 cert + ไม่รู้ว่าหายไปไหน

**Fix:** ตอบ header `X-Missing-Certs: 5` หรือใส่ note ใน PDF cover page

---

### BUG-16 — Filename Truncation ใน DB Columns

**ตำแหน่ง:** Multiple models

```python
# job.py:25 — courses ใน JSON เก็บ string ของ id อาจยาว
total_price = Column(String(10))   # ← 10 chars max — "12345678" หมดแล้ว
total_hours = Column(String(10))
nid_hash = Column(String(64))      # OK สำหรับ SHA-256

# certificate.py:14
course_id = Column(String(20))     # ← OK (SET ids ≤ 6 digits)

# payment.py:18
amount = Column(String(10))        # ← "verified-by-admin" (18 chars) → truncate!
```

```python
# admin.py:58
payment.amount = "verified-by-admin"   # ← 18 chars but column = 10 → error PG
```

PostgreSQL จะ raise `StringDataRightTruncation` ตอน commit — admin panel jammed

---

### BUG-17 — JobLog.progress Field Width = 5 Chars

**ตำแหน่ง:** `app/models/job_log.py:18`

```python
progress = Column(String(5), nullable=True)  # "73" = 73%
```

5 chars OK — "100" / "100%" ผ่าน
แต่ถ้าใครส่ง "100.0%" (6 chars) → truncate / error

`tasks.py` log:
```python
await log("ok", "เข้าระบบสำเร็จ — กำลัง SSO ไป SET")  # no progress, OK
await on_log("sys", f"[{i}/{total}] เริ่มหลักสูตร {course_id}")  # no progress
```

ปัจจุบันส่งเป็น string ของ int → ไม่เกิน 3 chars → OK
แต่ JobLog.message = `String(512)` — บาง message ของ exception อาจยาว:
```python
await log_job(db, job_id, "err", f"เกิดข้อผิดพลาด: {str(e)[:200]}")  # OK truncated
```

ตรงนี้ truncate เอง — แต่ถ้าลืม `[:200]` ที่อื่น → fail

---

### BUG-18 — Race Condition: Reference Set ก่อน Check Duplicate

**ตำแหน่ง:** `app/api/payments.py:163-173`

```python
# ตรวจซ้ำ
if ocr_reference:
    with db.no_autoflush:
        dup_result = await db.execute(
            select(Payment).where(
                Payment.reference == ocr_reference,
                Payment.id != payment.id,
            )
        )
    if dup_result.scalar_one_or_none():
        errors.append("สลิปนี้เคยใช้กับ job อื่นแล้ว")
```

ภายในระหว่าง check และ `payment.reference = ocr_reference` — concurrent verify 2 jobs ที่ใช้ slip เดียวกัน:

```
t=0  Job A: SELECT → no dup → set ref → commit → OK
t=0  Job B: SELECT → no dup → set ref → commit → ❌ IntegrityError
```

Code มี `except IntegrityError` แต่ rollback แล้ว return error generic — UX OK, แต่ status code 422 ทั้งคู่ขัดแย้งกับสิ่งที่ user เห็น

---

### BUG-19 — Slip Datetime Comparison ใช้ Naive

**ตำแหน่ง:** `app/api/payments.py:181-186`

```python
now_th = datetime.now(timezone.utc) + timedelta(hours=7)
now_th_naive = now_th.replace(tzinfo=None)
age = now_th_naive - slip_dt
```

ทำเองด้วย hardcoded +7 แทน `pytz.timezone("Asia/Bangkok")` — ถ้า DST/leap จะเพี้ยน (Thailand ไม่มี DST แต่ pattern ผิด)

นอกจากนั้น `slip_dt` มาจาก:
- OCR `_parse_datetime()` → returns naive datetime
- SlipOK `utils/slipok.py` → convert UTC → +7 → naive datetime (ถูก)

ดี — แต่เปราะบาง

---

### BUG-20 — DSL Login Timing-Attack Surface

**ตำแหน่ง:** `app/api/courses.py:39-58`

```python
@router.post("/fetch", response_model=List[CourseOut])
async def fetch_courses(req: FetchCoursesRequest):
    async with DSLClient() as client:
        ok = await client.login(req.nid, req.pwd)
        if not ok:
            raise HTTPException(401, detail="Login ไม่สำเร็จ ...")
```

ทุก request spawn Playwright headless Chromium (~200MB RAM, 3-5s startup) — ใช้ทำ DDoS ฟรีๆ

ไม่มี rate limit, ไม่มี captcha, ไม่มี auth ก่อน fetch_courses

**Fix:** require JWT login + rate limit per IP + per user

---

### BUG-21 — Worker ไม่ Cleanup Slip/Cert ถ้า Job Failed

**ตำแหน่ง:** `app/worker/tasks.py:117-122`

```python
except Exception as e:
    await log_job(db, job_id, "err", f"เกิดข้อผิดพลาด: {str(e)[:200]}")
    job.status = JobStatus.failed
    await db.commit()
finally:
    await client.close()
```

ไม่ลบไฟล์ slip + cert dir ที่ออกครึ่งทาง

ระยะยาว: `./uploads/slips/` กับ `./uploads/certs/{job_id}/` พองเรื่อยๆ ไม่มี GC

**Fix:** เพิ่ม cleanup task ใน Celery beat ทุก 7 วันลบ `failed` jobs + ไฟล์

---

### BUG-22 — Redis Credentials TTL 30 นาที (อาจสั้นไป)

**ตำแหน่ง:** `app/api/jobs.py:90-91`

```python
await redis.setex(f"job:{job.id}:nid", 1800, encrypt_password(payload.nid))
await redis.setex(f"job:{job.id}:pwd", 1800, encrypt_password(payload.pwd))
```

ถ้า:
1. User สร้าง job (NID/PWD ใน Redis, TTL=30min)
2. User ไปจ่ายเงิน แต่ slip ติด captcha / SMS verify นาน
3. กลับมา 35 นาทีเสร็จ → submit verify → ผ่าน → dispatch worker
4. Worker อ่าน NID/PWD → expired → "ไม่พบ session"

**Fix:** TTL 2 ชั่วโมง + รีเซ็ต TTL ตอน verify success
```python
# extend TTL after payment verified
await redis.expire(f"job:{job.id}:nid", 1800)
```

---

### BUG-23 — DSLClient Concurrency Race ใน Worker Process

**ตำแหน่ง:** `app/worker/celery_app.py:18-20`

```python
worker_prefetch_multiplier=1,   # 1 job ต่อ worker
```

OK ถ้า prefetch=1 แต่ ถ้า scale up เป็น `--concurrency=4` (4 child processes) → 4 workers run พร้อมกัน → 4 Chromium instance พร้อมกัน → RAM/CPU spike

นอกจากนี้ `/tmp/exam_answer_cache.json` ถูกใช้ร่วมกัน → race condition ตอน `_save_answer_cache`:
```python
with open("/tmp/exam_answer_cache.json", "w") as f:
    json.dump(cache, f, ensure_ascii=False, indent=2)  # ← เขียนทับโดยไม่ lock
```

2 workers เขียนพร้อมกัน → ไฟล์ corrupt → load fail → cache reset

**Fix:** ใช้ `fcntl.flock` หรือ atomic rename pattern หรือ Redis hash แทนไฟล์

---

### BUG-24 — Exam Type Mapping Confusing

**ตำแหน่ง:** `dsl_client.py:763`

```python
# type=1 → pre_test_percentage
# type=3 → exam_percentage (ทั้งที่ชื่อ "post-test")
# type=4 → post_test_percentage (ทั้งที่ชื่อ "exam")
# type=5 → survey
type_n = {"pre-test": 1, "post-test": 4, "exam": 3}.get(exam_type, 3)
```

Changelog 2026-05-18 confirms "field ใน enroll response สลับชื่อกับ type จริง" — แต่ก็เปราะบาง ถ้า SET เปลี่ยน mapping → ระบบเงียบ

**Fix:** ตอน Verify, read enroll response และ assert mapping ตรง

---

### BUG-25 — `_request_and_download_cert` ส่ง Cert Body Default `"lang":"th"`

**ตำแหน่ง:** `dsl_client.py:1213-1232`

```python
for attempt in range(3):
    cert_gen = await self.page.evaluate(f"""async () => {{
        try {{
            const r = await fetch('/api/site/enroll/{enroll_id}/certificate', {{
                method: 'POST', credentials: 'include',
                headers: {{...}}, body: JSON.stringify({{lang:'th'}}),
            }});
```

แค่ 3 ครั้ง × 2.5s = 7.5s total — ถ้า SET generate cert ช้ากว่านี้ → return None
return None แล้ว worker ไม่ retry — แค่ log "warn ดาวน์โหลดวุฒิบัตรไม่ได้"

Comment บอกว่า "background retry" แต่ **ไม่มี background retry จริงในโปรเจกต์!** — เป็น TODO

```python
return None   # ← Job เดินต่อ จบที่ status=done แต่ cert ไม่ครบ
```

User download bundle = ขาดบางหลักสูตร ไม่รู้ตัว

**Fix:** เพิ่ม Celery beat task `retry_pending_certs` ทุก 15 นาที

---

### BUG-26 — Pre-test ตอบ Option 0 ทุกข้อ → SET Anti-cheat Trigger

**ตำแหน่ง:** `dsl_client.py:899-902`

```python
if exam_type == "pre-test":
    s, t, _, _ = await _submit([0] * n)
    logger.info(f"  ✅ pre-test: submit {s}/{t} (ไม่ต้องผ่าน)")
    return
```

Pre-test ตอบ option 0 ทุกข้อทุกหลักสูตร → SET อาจตรวจจับ pattern นี้ → flag account

**Fix:** Random index แทน (`random.randint(0, n_opts-1)`)

---

### BUG-27 — `JobOut.courses` ตั้งเป็น `List[str]` แต่ DB เป็น JSON

**ตำแหน่ง:** `app/schemas/job.py:50` + `app/models/job.py:26`

```python
# models
courses = Column(JSON, nullable=False)   # raw JSON

# schemas
courses: List[str]   # pydantic จะ coerce แต่ถ้า DB มี int → str(int)
```

ถ้า frontend ส่งบาง course_id เป็น int (Python int json.loads) → DB เก็บ int → Pydantic v2 strict mode อาจ fail

ปัจจุบัน `JobCreate.validate_courses` ทำ:
```python
cleaned = [str(c).strip() for c in v if str(c).strip()]
```
ทำให้ string ทั้งหมด — OK

แต่ admin หรือ migration จะ insert ตรง → ระวัง

---

### BUG-28 — Admin Force-Verify ไม่ตรวจ `payment.verified` ก่อน

**ตำแหน่ง:** `app/api/admin.py:44-67`

```python
@router.post("/jobs/{job_id}/force-verify")
async def force_verify(job_id: str, db: AsyncSession = Depends(get_db)):
    ...
    payment.verified = True
    payment.verified_at = datetime.now(timezone.utc)
    payment.amount = "verified-by-admin"   # ← bug 16 truncate!

    job.status = JobStatus.queued
    await db.commit()

    run_automation.delay(str(job_id))   # ← bug 1 double-dispatch ถ้า job ยัง running
```

ไม่ดู status — ถ้า admin คลิก force-verify ขณะ worker กำลังทำงาน → dispatch ซ้ำ

---

### BUG-29 — `slipok.py` Filename Slice ผิดบน Windows

**ตำแหน่ง:** `app/utils/slipok.py:68`

```python
files={"files": (slip_path.rsplit("/", 1)[-1], file_bytes, "image/jpeg")}
```

`rsplit("/", 1)` ไม่จับ Windows separator `\` — path `C:\uploads\slips\abc.jpg` → ส่งทั้ง path เป็น filename ไป SlipOK

ใช้ `Path(slip_path).name` แทน

---

## 🟢 MEDIUM — Code Quality / UX

### BUG-30 — `start()` ขาด `channel="chrome"` Argument

**ตำแหน่ง:** `dsl_client.py:57`

```python
self.browser = await self.pw.chromium.launch(
    headless=self.headless, slow_mo=100 if DEBUG else 0
)
```

Memory บอกว่า "ใช้ system Chrome แทน bundled Chromium" + `channel="chrome"` แก้ side-by-side DLL error บน Windows — แต่ในไฟล์จริง **ไม่มี channel argument**

ไฟล์ที่ user download อาจเป็น snapshot ก่อนหน้า fix

---

### BUG-31 — `_dismiss_popups` Escape Key Fallback Reset Angular State

**ตำแหน่ง:** `dsl_client.py:93-97`

```python
try:
    await self.page.keyboard.press("Escape")
    await self.page.wait_for_timeout(300)
    logger.info("🚪 ส่ง Escape เผื่อปิด popup")
except Exception:
    pass
```

`_sso_click_and_capture` comment บอก:
```python
# รอให้ Angular render click handler เสร็จ (ไม่ dismiss popup ก่อน — Escape รบกวน Angular state)
```

แต่ใน `goto_set` → `_dismiss_popups` ถูกเรียกหลัง SSO — ถ้า Escape ถูกกด → Angular state breaks → SET list page render ไม่ครบ → fetch_courses pagination fail

**Fix:** เปลี่ยน Escape fallback เป็น optional flag, ไม่ใช่ default

---

### BUG-32 — `_goto_next_page` Duplicate `wait_for_selector`

**ตำแหน่ง:** `dsl_client.py:401-405`

```python
try:
    await self.page.wait_for_selector("a.card-course", timeout=10_000)
except Exception:
    await self.page.wait_for_timeout(1500)
try:
    await self.page.wait_for_selector("a.card-course", timeout=10_000)
except Exception:
    pass
return True
```

มี 2 `wait_for_selector` ติดกันใน path เดียว — double wait (20s waste ถ้าทั้ง 2 fail)

---

### BUG-33 — `_collect_lessons` Mixed Logic Hours Parsing

**ตำแหน่ง:** `dsl_client.py:338-341`

```javascript
if (hMatch) hours = parseFloat(hMatch[1]);
else if (mMatch) hours = Math.round(parseInt(mMatch[1]) / 60 * 10) / 10;
```

ถ้า text มีทั้ง "1 ชั่วโมง 30 นาที" → จับแค่ hours 1 ละเลย 30 นาที = 0.5

**Fix:** sum ทั้งคู่
```javascript
let hours = 0;
if (hMatch) hours += parseFloat(hMatch[1]);
if (mMatch) hours += parseInt(mMatch[1]) / 60;
```

---

### BUG-34 — `JobCreate.courses` ไม่ตรวจ Duplicate

**ตำแหน่ง:** `app/schemas/job.py:27-35`

```python
@field_validator("courses")
@classmethod
def validate_courses(cls, v: List[str]) -> List[str]:
    if len(v) == 0:
        raise ValueError("ต้องเลือกอย่างน้อย 1 หลักสูตร")
    cleaned = [str(c).strip() for c in v if str(c).strip()]
    if not cleaned:
        raise ValueError("course id ว่าง")
    return cleaned
```

ส่ง `["1941", "1941", "1941"]` ผ่าน → บอททำ 1941 รอบ 3 ครั้ง → SET trigger anti-cheat

**Fix:** `cleaned = list(dict.fromkeys(cleaned))`

---

### BUG-35 — Anti-Cheat อาจ Lock Account ถ้า Submit เยอะ

**ตำแหน่ง:** `dsl_client.py:911-915`

```python
# ลด MAX_ATTEMPTS เป็น 3 กัน anti-cheat trigger
MAX_ATTEMPTS = 3
```

3 attempts ดี แต่ logs ใน Thai บอกว่า post-test + exam แยกกัน → ทำ exam 6 submit (3+3) + survey 1 + pre-test 1 = 8 submit/หลักสูตร

ถ้า user เลือก 10 หลักสูตร → 80 submit ต่อ session → SET อาจ rate limit

**Fix:** เพิ่ม delay random 5-15s ระหว่าง courses

---

### BUG-36 — Frontend Static Has No Cache Headers

**ตำแหน่ง:** `app/main.py:27`

`StaticFiles` default ไม่ set Cache-Control → ทุก request โหลดใหม่ทั้ง `.jsx`

---

### BUG-37 — `WS /ws/jobs/{id}` ไม่ Close DB Session ที่ Properly

**ตำแหน่ง:** `app/api/ws.py:19-25`

```python
async with AsyncSessionLocal() as db:
    result = await db.execute(...)
    job = result.scalar_one_or_none()

# session ปิดแล้วก่อนใช้ job.logs (ที่ load eager แล้ว) — OK
```

ตรงนี้ใช้ `selectinload(Job.logs)` แล้ว close session — OK. แต่ถ้าโค้ดอนาคตเพิ่ม lazy access → DetachedInstanceError

ถ้า websocket connection หลุดก่อน `pubsub.aclose()` ที่ finally → connection leak

---

### BUG-38 — `inspect()` ของ Celery Block ใน Sync Function

ที่กล่าวใน BUG-4 — ไม่มี graceful degradation. ถ้า Redis down → ping raise → catch → return False → 503 — แต่ user เจอ "ระบบบอทกำลังปิดปรับปรุง" แม้แค่ Redis hiccup

---

### BUG-39 — JWT ไม่ใช้ `iat` / `nbf` / `jti`

**ตำแหน่ง:** `app/utils/security.py:44-50`

```python
def create_access_token(user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.access_token_expire_hours)
    return jwt.encode(
        {"sub": user_id, "email": email, "exp": expire},
        ...
    )
```

- ไม่มี `jti` → revoke ไม่ได้
- ไม่มี `iat`/`nbf` → replay attack window 24h
- email อยู่ใน payload (PII)

---

### BUG-40 — `JobOut.id` UUID vs Pydantic Schema

**ตำแหน่ง:** `app/schemas/job.py:48`

```python
class JobOut(BaseModel):
    id: UUID
    ...
```

`JobOut` return จาก endpoint จะ serialize UUID → string OK ใน Pydantic v2. แต่ frontend คาดหวัง `string` — ถ้าเปลี่ยนเป็น Pydantic v1 จะ break

---

### BUG-41 — Promptpay QR ใช้ `expected_account` แบบ raw

**ตำแหน่ง:** `app/api/payments.py:60-62`

```python
account = "".join(c for c in settings.expected_account if c.isdigit())
payload = promptpay_qr.generate_payload(account, amount)
```

`promptpay` library ต้องการ:
- 10-digit mobile number, หรือ
- 13-digit citizen ID, หรือ
- 15-digit eWallet ID

ถ้า admin set `EXPECTED_ACCOUNT=099-XXX-XXX-4` → digits = "0994" (4 chars) → library raise / สร้าง QR ผิด

`.env.example` ก็ไม่มี `EXPECTED_ACCOUNT` field — admin จะใช้ default placeholder

---

## 📋 สรุป Priority Fix

| Priority | Bug# | สิ่งที่ต้องแก้ | Effort |
|---|---|---|---|
| P0 🔴 | 1, 2 | ลบ dispatch จาก create_job + เช็ค status/payment ใน worker | 30 นาที |
| P0 🔴 | 3 | ส่ง redis client เข้า log_job | 15 นาที |
| P0 🔴 | 4 | wrap _celery_worker_alive ใน run_in_executor | 10 นาที |
| P0 🔴 | 9 | คำนวณ total_price server-side | 1 ชั่วโมง |
| P1 🟡 | 6, 7 | Auth ownership + ตรวจ default secrets | 2 ชั่วโมง |
| P1 🟡 | 8 | CORS whitelist | 5 นาที |
| P1 🟡 | 14 | `/tmp/` → `tempfile.gettempdir()` | 15 นาที |
| P1 🟡 | 22 | TTL Redis 2 ชั่วโมง + extend on verify | 15 นาที |
| P2 🟢 | 5, 13, 25 | Edge case fixes + Celery beat retry | 1 วัน |
| P3 🟢 | อื่นๆ | Cleanup ทีละจุด | progressive |

---

## 🎯 Recommended Next Actions

1. **ทำ Hotfix ทันที (P0):** Bug 1, 2, 3, 4 — ใช้เวลา ~1 ชม. แต่กระทบ money flow
2. **Patch ก่อน Production (P1):** Bug 6, 7, 8, 9 — security baseline
3. **Schedule (P2):** เพิ่ม Celery beat task สำหรับ retry cert + cleanup uploads
4. **Refactor (long-term):** เพิ่ม `Job.user_id` FK + cleanup auth coverage

---

## 🔍 จุดที่ยังต้อง Verify ต่อ

- [ ] Frontend `app.jsx` flow ที่เรียก API — ตรวจว่ามี client-side cache ของ total_price หรือไม่
- [ ] รัน `pytest` (ถ้ามี test suite) — ไม่เห็น test ในโปรเจกต์
- [ ] รัน load test — Playwright per-request scaling
- [ ] เช็ค `.env` ที่ใช้จริง (ใน `D:\terminter01\gyso-backend-main`) ว่า SECRET_KEY/ADMIN_PASSWORD ตั้งแล้ว
