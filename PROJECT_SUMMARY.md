# GYSO Backend — Detailed Project Summary

> **Purpose:** An automated service that completes volunteer-hour courses on the SET e-Learning portal
> on behalf of Thai student-loan (กยศ) borrowers. Users pay a fee, upload a payment slip,
> and the system's Playwright bot logs in, finishes every selected course, and returns PDF certificates.

---

## Table of Contents

1. [Technology Stack](#1-technology-stack)
2. [Project Structure](#2-project-structure)
3. [Configuration & Environment](#3-configuration--environment)
4. [Database Models](#4-database-models)
5. [API Endpoints](#5-api-endpoints)
6. [Automation Engine (DSLClient)](#6-automation-engine-dslclient)
7. [Payment Verification](#7-payment-verification)
8. [Quiz Solving Strategy](#8-quiz-solving-strategy)
9. [Real-time Logging (WebSocket + Redis Pub/Sub)](#9-real-time-logging-websocket--redis-pubsub)
10. [Security Design](#10-security-design)
11. [Celery Task Worker](#11-celery-task-worker)
12. [Frontend](#12-frontend)
13. [Infrastructure (Docker)](#13-infrastructure-docker)
14. [Full Job Lifecycle (End-to-End Flow)](#14-full-job-lifecycle-end-to-end-flow)

---

## 1. Technology Stack

| Layer | Library / Tool |
|---|---|
| Web framework | **FastAPI 0.115** (async, ASGI) |
| ORM | **SQLAlchemy 2.0** (async engine + `asyncpg`) |
| Database | **PostgreSQL 16** |
| Task queue | **Celery 5.4** |
| Message broker / cache | **Redis 7** |
| Browser automation | **Playwright 1.47** (Chromium, headless) |
| OCR | **pytesseract 0.3** + **Pillow 10** |
| Payment verification | **SlipOK API** (primary) / pytesseract OCR (fallback) |
| PromptPay QR | **promptpay 1.1.9** |
| LLM (quiz answering) | **Google Gemini 2.5 Flash** via REST API |
| Encryption | **AES-256-GCM** (`cryptography` library) |
| Auth | **JWT** (`python-jose`) + **bcrypt** (`passlib`) |
| HTTP client | **httpx 0.28** |
| Schema validation | **Pydantic v2** |
| Migrations | **Alembic 1.13** |

---

## 2. Project Structure

```
gyso-backend-main/
├── app/
│   ├── main.py              # FastAPI app entry point, router mounting, static files
│   ├── config.py            # Settings (pydantic-settings, reads .env)
│   ├── database.py          # Async engine + session factory + Base model
│   ├── api/
│   │   ├── jobs.py          # Job CRUD + certificate download endpoints
│   │   ├── payments.py      # Payment info, QR generation, slip verification
│   │   ├── courses.py       # Fetch available courses from SET portal
│   │   ├── auth.py          # User register / login / JWT / DSL credentials
│   │   ├── admin.py         # Admin panel API (HTTP Basic auth)
│   │   └── ws.py            # WebSocket endpoint for real-time job logs
│   ├── models/
│   │   ├── user.py          # User + UserDSLCredential tables
│   │   ├── job.py           # Job table (status enum, course list JSON)
│   │   ├── payment.py       # Payment table (slip path, OCR results, verified flag)
│   │   ├── certificate.py   # Certificate table (PDF file path per course per job)
│   │   └── job_log.py       # JobLog table (real-time progress entries)
│   ├── schemas/
│   │   ├── job.py           # JobCreate, JobOut Pydantic models
│   │   ├── payment.py       # PaymentOut Pydantic model
│   │   └── auth.py          # RegisterIn, LoginIn, TokenOut, UserOut, DSLCredentialIn
│   ├── utils/
│   │   ├── security.py      # AES-GCM encrypt/decrypt, SHA-256 hash, JWT, bcrypt
│   │   ├── ocr.py           # Slip OCR (amount, reference, recipient, datetime, bank)
│   │   ├── slipok.py        # SlipOK API client (primary slip verification)
│   │   ├── llm_answer.py    # Gemini API client (quiz answering)
│   │   ├── job_logger.py    # Writes JobLog to DB + publishes to Redis pub/sub
│   │   └── redis_client.py  # Shared Redis async client singleton
│   └── worker/
│       ├── celery_app.py    # Celery app configuration
│       ├── tasks.py         # run_automation Celery task
│       └── dsl_client.py    # DSLClient: full Playwright automation engine
├── alembic/                 # Database migration scripts
│   └── versions/
│       ├── 4d4dac26ccac_initial_tables.py
│       ├── 7c7816cb8a1a_add_reference_and_rec...
│       └── b3e9f1a2c4d5_add_users_auth.py
├── frontend/
│   ├── SLF Auto Volunteer.html  # Main user-facing page
│   ├── admin.html               # Admin dashboard
│   ├── app.jsx                  # Main React-like frontend logic
│   ├── auth.jsx                 # Login/register UI
│   ├── sections.jsx             # Page section components
│   ├── tweaks-panel.jsx         # Settings panel
│   ├── icons.jsx                # SVG icon components
│   └── motion-shim.jsx          # Animation shim
├── scripts/                 # 30+ one-off Playwright debug/inspection scripts
├── docker-compose.yml       # PostgreSQL + Redis containers
├── requirements.txt         # Python dependencies
├── alembic.ini              # Alembic config
└── .env.example             # Environment variable template
```

---

## 3. Configuration & Environment

All settings are managed via `app/config.py` using **pydantic-settings** (reads `.env` file).

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://gyso:gyso1234@localhost:5432/gyso_db` | PostgreSQL connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for Celery broker + pub/sub |
| `SECRET_KEY` | `change-this-...` | AES-GCM key derivation + JWT signing |
| `UPLOAD_DIR` | `./uploads` | Root directory for uploaded slips and cert PDFs |
| `ADMIN_PASSWORD` | `admin1234` | HTTP Basic password for `/admin/*` routes |
| `EXPECTED_ACCOUNT` | `099-XXX-XXX-4` | PromptPay / bank account (last 4 digits used for matching) |
| `EXPECTED_RECIPIENT_NAME` | _(empty)_ | Substring check on slip recipient name |
| `EXPECTED_BANK_KEYWORDS` | KBank, SCB, BBL, … | Allowed banks (comma-separated) |
| `SLIP_MAX_AGE_MINUTES` | `30` | Reject slips older than this many minutes (0 = disabled) |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_HOURS` | `24` | JWT TTL |
| `SLIPOK_API_KEY` | _(empty)_ | SlipOK API key (leave empty to use OCR fallback) |
| `SLIPOK_BRANCH_ID` | _(empty)_ | SlipOK branch ID |
| `GEMINI_API_KEY` | _(empty)_ | Google Gemini API key (leave empty to disable AI answering) |

---

## 4. Database Models

### `users`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | Auto-generated |
| `email` | String (unique, indexed) | Lowercased on insert |
| `hashed_password` | String | bcrypt hash |
| `is_active` | Boolean | Default `true` |
| `is_admin` | Boolean | Default `false` |
| `created_at` / `updated_at` | DateTime(tz) | Auto-managed |

### `user_dsl_credentials`
Stores DSL portal login credentials encrypted with AES-GCM.

| Column | Notes |
|---|---|
| `user_id` | FK → `users.id` (1-to-1) |
| `nid_encrypted` | Citizen ID encrypted with AES-256-GCM |
| `pwd_encrypted` | Password encrypted with AES-256-GCM |

### `jobs`
Central tracking table for each automation request.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | |
| `nid_hash` | String(64) | SHA-256 of citizen ID — never stores raw NID |
| `courses` | JSON | e.g. `["anti", "fin", "123456"]` |
| `total_price` | String | Total price in THB |
| `total_hours` | String | Total hours |
| `status` | Enum | `pending → queued → running → done / failed` |
| `completed_at` | DateTime | Set when status = `done` |

### `payments`
One-to-one with `jobs`. Tracks slip file and verification result.

| Column | Notes |
|---|---|
| `slip_path` | Local file path of uploaded slip image |
| `amount` | Amount read by OCR/SlipOK |
| `reference` | Unique reference code (prevents duplicate-slip reuse) |
| `recipient` | Last-4-digits of destination account |
| `verified` | Boolean — must be `true` before job enters queue |
| `verified_at` | Timestamp of verification |

### `certificates`
One record per course per job.

| Column | Notes |
|---|---|
| `job_id` | FK → `jobs.id` |
| `course_id` | e.g. `"anti"`, `"123456"` |
| `pdf_path` | Local path to downloaded PDF certificate |

### `job_logs`
Append-only progress log entries, readable via WebSocket.

| Column | Notes |
|---|---|
| `job_id` | FK → `jobs.id` |
| `type` | `"ok"` / `"sys"` / `"play"` / `"done"` / `"err"` / `"warn"` |
| `message` | Human-readable status message (Thai) |
| `progress` | Percentage string `"0"`–`"100"` |

---

## 5. API Endpoints

### Jobs — `/jobs`

| Method | Path | Description |
|---|---|---|
| `POST` | `/jobs/` | Create job: accepts `nid`, `pwd`, `courses` (JSON), `total_price`, `total_hours`, `slip` (file). Encrypts credentials → Redis, saves slip, triggers Celery task. Returns `JobOut`. |
| `GET` | `/jobs/{job_id}` | Get job status + all log entries. |
| `GET` | `/jobs/{job_id}/certificates` | List certificates for this job (course_id, ready flag, download URL). |
| `GET` | `/jobs/{job_id}/certificate?course_id=X` | Download single certificate PDF. |
| `GET` | `/jobs/{job_id}/certificates/bundle` | Merge all certificate PDFs into one file and stream it. |

### Payments — `/payments`

| Method | Path | Description |
|---|---|---|
| `GET` | `/payments/info` | Return payment account info (account number, recipient name, method). |
| `GET` | `/payments/qr?amount=N` | Generate PromptPay QR code (EMVCo format) as PNG for a given amount. |
| `GET` | `/payments/{job_id}/qr` | Generate PromptPay QR locked to `job.total_price`. |
| `POST` | `/payments/{job_id}/verify` | Verify payment slip via SlipOK API or OCR. Runs 6 checks. If all pass → `payment.verified = true`, job status = `queued`, triggers Celery. |
| `GET` | `/payments/{job_id}` | Get payment record for a job. |

### Courses — `/courses`

| Method | Path | Description |
|---|---|---|
| `POST` | `/courses/fetch` | Login to DSL portal with user credentials, SSO to SET, scrape all available (incomplete) courses with their hours and computed price. |
| `GET` | `/courses/price-rate` | Return `{"baht_per_hour": 3}`. |

### Auth — `/auth`

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/register` | Register new user (email + password). |
| `POST` | `/auth/login` | OAuth2 password login → returns JWT `access_token`. |
| `GET` | `/auth/me` | Get current user profile. |
| `POST` | `/auth/credentials` | Save DSL portal NID + password (AES-GCM encrypted) to user account. |
| `DELETE` | `/auth/credentials` | Delete saved DSL credentials. |

### Admin — `/admin`
Requires HTTP Basic auth (`admin` / `ADMIN_PASSWORD`).

| Method | Path | Description |
|---|---|---|
| `GET` | `/admin/jobs` | List all jobs (descending by created_at). |
| `POST` | `/admin/jobs/{job_id}/force-verify` | Bypass slip verification → queue job immediately (for testing). |
| `DELETE` | `/admin/jobs/{job_id}` | Delete job and all related records (logs, certs, payment). |

### WebSocket — `/ws`

| Path | Description |
|---|---|
| `/ws/jobs/{job_id}` | Subscribe to live log stream. On connect: sends `snapshot` event (full existing logs + current status). Then streams `log` events as the worker publishes them via Redis pub/sub. Closes when `type = "done"` or `"err"` is received. |

### Static / Pages

| Path | Description |
|---|---|
| `GET /` | Serves `frontend/SLF Auto Volunteer.html` (user-facing page) |
| `GET /admin-panel` | Serves `frontend/admin.html` |
| `GET /health` | Health check → `{"status": "ok"}` |

---

## 6. Automation Engine (DSLClient)

**File:** `app/worker/dsl_client.py`

`DSLClient` is a Playwright-based browser automation class targeting two portals:
- **DSL Portal:** `https://wsa.dsl.studentloan.or.th` (Angular SPA, hash routing)
- **SET e-Learning:** `https://elearning.set.or.th/SETStudentLoan`

### Constants

```python
VIDEO_SPEED = 16          # Video playback speed multiplier
WATCH_TIMEOUT_SEC = 1800  # Safety cap per video clip (30 min)
PRICE_PER_HOUR = 3        # Baht per course hour
```

### Key Methods

#### `login(nid, pwd) → bool`
1. Navigate to `/#/rms/rms-login`
2. Wait for `#citizenFld` field
3. Call `_dismiss_popups()` to close any announcement modals (tries 13+ selectors + Escape key)
4. Type NID and password with realistic delay (`delay=30ms`)
5. Click `#signInBtn`
6. Wait for URL hash to no longer contain `rms-login` (success) or detect error messages (failure)

#### `goto_set() → bool`
SSO from DSL to SET e-Learning.
1. Call `_sso_click_and_capture()`: click `#routeSETBtn`, capture the new tab Angular opens
2. Navigate to `SET_LIST_URL` and confirm URL contains `/list` (SSO success)

#### `fetch_courses() → List[Dict]`
Scrapes all incomplete courses from SET e-Learning.
1. Navigate to `/list`
2. Paginate through all pages using `_scrape_current_page()` (scrapes `a.card-course` cards)
3. For each course card, extract: `id`, `code`, `title`, `hours`, `card_completed` flag
4. Call `_filter_incomplete()`:
   - Fast-path: skip cards with "completed" badge
   - Batch-fetch course enrollment status via the SET API inside the browser page (JS `fetch` calls injected via `page.evaluate`)
   - Check `certificate_datetime` — if present, course is done → skip
   - Set `status`: `"not_enrolled"` / `"not_started"` / `"in_progress"` 
5. Return only incomplete courses, each with computed `price = hours × 3`

#### `complete_course_via_api(course_id, on_log, cert_dir) → Optional[str]`
**The main automation method.** Completes a course entirely via the SET API (no real video playback required).

**Step 1 — Get course info & enroll_id:**
```
GET /api/site/groups/SETStudentLoan/courses/{course_id}
```

**Step 2 — Enroll (if not already enrolled):**
```
POST /api/site/enroll2learning
body: cid={course_id}&tid=&type=&pid=&ftype=
```

**Step 3 — Fetch topics list:**
```
GET /api/site/enroll/{enroll_id}
```
Recursively extract all leaf `vod` topics (nested `parent` arrays).

**Step 4 — Mark each topic complete:**
For each incomplete topic (percentage < 100):
1. `POST /api/site/enroll2topic_stage` — create enroll2topic record if missing
2. `POST /api/site/enroll/views` — register a view event
3. Refetch `enroll_id` to get `enroll2topic_id`
4. `POST /api/site/enroll2topic_duration` body: `id={e2t_id}&duration=0`
5. `POST /api/site/enroll2topic_status` body: `id={e2t_id}&status=1`

All API calls are injected as JavaScript `fetch` inside the SET browser context (so cookies/XSRF tokens are automatically included).

**Step 5 — Pre-test:** Submit once with any answers (no pass score required).

**Step 6 — Post-test:** Submit and attempt to pass ≥70%. See [Quiz Solving Strategy](#8-quiz-solving-strategy).

**Step 7 — Exam:** Same as post-test.

**Step 8 — Survey:** Navigate to `/enroll/{enroll_id}/summary`, expand all Bootstrap accordions, select first radio for every question group, click `#submit-an-survey`, confirm popup, verify `survey_datetime != null`.

**Step 9 — Certificate:** Call `POST /api/site/enroll/{enroll_id}/certificate` with `{"lang":"th"}`. If `certificate_datetime` is returned, download PDF via `GET /api/site/enroll/{enroll_id}/certificate/th` (returned as base64, written to disk).

#### `watch_course(course_id, on_log, cert_dir)` *(legacy)*
The original video-watching flow (still in the codebase but superseded by `complete_course_via_api`):
1. Navigate to course page, click enroll button
2. Collect all lesson links via `_collect_lessons()`
3. For each lesson: set `video.playbackRate = 16`, mute, play, poll until `video.ended`
4. Handle iframe-embedded videos
5. Do quiz via `_do_quiz()` (selects first option for every question)
6. Download certificate via `_download_cert()`

---

## 7. Payment Verification

**File:** `app/api/payments.py` — `POST /payments/{job_id}/verify`

### Verification Pipeline

```
Upload slip → POST /jobs/ (slip saved to disk)
                │
                ▼
         POST /payments/{job_id}/verify
                │
                ├── Try SlipOK API first
                │     ├── Success → use SlipOK data (amount, reference, recipient, datetime)
                │     └── SlipOK rejects → raise 422 immediately (no OCR fallback)
                │
                └── SlipOK not configured or API error
                      └── Fallback: pytesseract OCR
                            └── Preprocess image (grayscale, sharpen, contrast, resize)
                                → extract amount, reference, recipient, datetime, bank, name
```

### 6 Validation Checks

| # | Check | Skipped if |
|---|---|---|
| 1 | Amount matches `job.total_price` (±0.5 THB) | — |
| 2 | Recipient account last 4 digits match `EXPECTED_ACCOUNT` | SlipOK verified |
| 3 | Reference not already used by another job | — |
| 4 | Slip age ≤ `SLIP_MAX_AGE_MINUTES` (also rejects future-dated slips) | `SLIP_MAX_AGE_MINUTES = 0` |
| 5 | Bank is in `EXPECTED_BANK_KEYWORDS` list | SlipOK verified |
| 6 | Recipient name contains `EXPECTED_RECIPIENT_NAME` | SlipOK verified or name empty |

If all checks pass → `payment.verified = true`, `job.status = queued`, `run_automation.delay(job_id)` is called.

### OCR Details (`app/utils/ocr.py`)

- Image preprocessing: convert to grayscale → SHARPEN filter → 2× contrast → upscale to ≥800px
- `pytesseract` with `lang="tha+eng"` and `--psm 6` (uniform block of text)
- Regex parsers for: Thai-format amounts (`จำนวน`, `฿`, `THB`), transaction reference codes (8–30 alphanumeric chars), masked account numbers (last-4-digits), Thai+Gregorian date/time (auto-converts Buddhist Era years), bank names, recipient names

---

## 8. Quiz Solving Strategy

**File:** `app/worker/dsl_client.py` — `_submit_exam(enroll_id, exam_type)`

The quiz engine uses a 3-layer strategy with a maximum of **3 attempts** (limited to avoid triggering SET anti-cheat which disables certificate issuance):

### Layer 1 — Answer Cache
A persistent cache at `/tmp/exam_answer_cache.json` maps `SHA1(question_text)[:12]` → correct option value.
After each failed attempt, the engine opens the score page (`/enroll/{id}/exam/{e2q_id}/score`) and extracts correct answers by reading CSS class markers (`correct`, `text-success`, `is-correct`, `answer-correct`, `.bi-check-circle`).

### Layer 2 — Gemini AI (attempt 0 only)
If Gemini API key is configured, the full question set is sent in one call to `gemini-2.5-flash` with:
- Temperature = 0.1 (deterministic)
- Response format: `{"answers": [index, index, ...]}`
- Retry with exponential backoff (2s, 5s, 10s) on 429/5xx errors

Prompt describes the course domain (finance, investment, accounting, marketing) to improve accuracy.

### Layer 3 — Rotation Fallback
If Gemini unavailable or not enough options pass, rotate through option indices (`attempt % n_options`).

### Submission Flow (per attempt)
```
1. POST /api/site/enroll2quiz            → get enroll2quiz_id
2. POST /api/site/questions2answer       → submit answers (fire-and-forget)
3. Wait 3s → GET /api/site/exam/{qid}/history  → read score
4. If score ≥ 70% → done
5. Else → open score page → extract correct answers → update cache
6. Navigate back to exam page → try again
```

### Pre-test
Submitted exactly once with all answers = index 0 (no passing score required).

---

## 9. Real-time Logging (WebSocket + Redis Pub/Sub)

```
Worker (Celery) ──► log_job() ──► JobLog DB row
                              └──► Redis PUBLISH job:{id}:logs

Browser ──► WebSocket /ws/jobs/{id}
                └──► Redis SUBSCRIBE job:{id}:logs
                         └──► Forward JSON messages to browser
```

**`log_job(db, job_id, type, message, progress)`** (`app/utils/job_logger.py`):
1. Creates a `JobLog` record and commits to PostgreSQL
2. Publishes JSON `{"type", "message", "progress", "ts"}` to Redis channel `job:{job_id}:logs`

**WebSocket handler** (`app/api/ws.py`):
1. On connect: loads all existing `JobLog` rows and sends `snapshot` event (supports reconnect)
2. Subscribes to Redis pub/sub channel
3. Forwards every published message to the browser as `log` event
4. Disconnects when `type = "done"` or `"err"` is received

---

## 10. Security Design

### Credential Handling
```
User submits NID + password
       │
       ├── NID → SHA-256 hash → stored in jobs.nid_hash (non-reversible, for dedup)
       │
       └── NID + password → AES-256-GCM encrypt (key = SHA-256(SECRET_KEY))
                                   └── stored in Redis with 30-minute TTL
                                         └── Worker reads, decrypts, uses for login
                                               └── Deleted from Redis after job completes
```
Raw credentials are **never stored in the database**. The only DB field with user identity is `nid_hash` (irreversible).

### User Authentication
- Registration: passwords hashed with **bcrypt** (salt auto-generated)
- Login: returns a **JWT** (HS256, 24-hour expiry) signed with `SECRET_KEY`
- Protected routes use `OAuth2PasswordBearer` scheme → `get_current_user()` dependency

### Admin Authentication
- HTTP Basic auth (`admin` / `ADMIN_PASSWORD`)
- Applied as FastAPI dependency on all `/admin/*` routes

### Encryption Utilities (`app/utils/security.py`)
- `encrypt_password(pwd)` → `base64(nonce[12] + AES-GCM-ciphertext)`
- `decrypt_password(token)` → reverse of above
- `hash_nid(nid)` → `SHA-256(nid)` hex string
- `hash_password(pwd)` → bcrypt hash
- `verify_password(plain, hashed)` → bcrypt check
- `create_access_token(user_id, email)` → signed JWT
- `decode_access_token(token)` → dict or None

---

## 11. Celery Task Worker

**File:** `app/worker/tasks.py` — `run_automation` task

### Celery Configuration (`app/worker/celery_app.py`)
```python
broker = redis_url          # Redis as both broker and result backend
task_acks_late = True       # Acknowledge task only after completion (not on pickup)
worker_prefetch_multiplier = 1  # One job per worker at a time
task_track_started = True
timezone = "Asia/Bangkok"
```

### Task Execution Flow

```
run_automation(job_id)
   │
   ├── Create fresh asyncio event loop (avoids Playwright internal state collision)
   ├── Create fresh SQLAlchemy engine with NullPool (avoids cross-loop connection issues)
   ├── Create fresh Redis client in this event loop
   │
   ├── Load Job from DB
   ├── Set job.status = running
   │
   ├── Read encrypted NID + password from Redis (30-min TTL keys)
   │     └── If missing → log error, set status = failed, return
   │
   ├── Decrypt NID + password
   │
   ├── DSLClient.start() → launch headless Chromium
   ├── client.login(nid, pwd) → DSL portal login
   ├── client.goto_set() → SSO to SET e-Learning
   │
   ├── For each course_id in job.courses:
   │     ├── complete_course_via_api(course_id, on_log, cert_dir)
   │     │     └── Returns PDF path (or None)
   │     └── Save Certificate record to DB
   │
   ├── Set job.status = done, job.completed_at = now()
   ├── log_job("done", "งานเสร็จสมบูรณ์ ✅", "100")
   └── Delete NID + password keys from Redis
```

If any exception occurs: log error, set `job.status = failed`, close browser.

### Pre-flight Check
Before accepting a job (`POST /jobs/`), the API checks that at least one Celery worker is alive using `celery.control.inspect(timeout=1.5).ping()`. If no worker responds → HTTP 503.

---

## 12. Frontend

Static files served from `frontend/` directory at `/static/*`.

| File | Purpose |
|---|---|
| `SLF Auto Volunteer.html` | Main user page — served at `/` |
| `admin.html` | Admin dashboard — served at `/admin-panel` |
| `app.jsx` | Main application component (React-like JSX) |
| `auth.jsx` | Login / registration UI |
| `sections.jsx` | Course selection, payment, progress sections |
| `tweaks-panel.jsx` | Settings/configuration panel |
| `icons.jsx` | SVG icon components |
| `motion-shim.jsx` | Animation utility shim |

The frontend communicates with the backend via REST API calls and a WebSocket connection to `/ws/jobs/{job_id}` for live progress updates.

---

## 13. Infrastructure (Docker)

`docker-compose.yml` spins up two services:

```yaml
postgres:
  image: postgres:16-alpine
  environment: POSTGRES_USER=gyso, POSTGRES_PASSWORD=gyso1234, POSTGRES_DB=gyso_db
  ports: 5432:5432
  volumes: postgres_data (persistent)

redis:
  image: redis:7-alpine
  ports: 6379:6379
```

The FastAPI server and Celery worker are run separately (not in Docker Compose), typically:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
celery -A app.worker.celery_app.celery worker --loglevel=info
```

---

## 14. Full Job Lifecycle (End-to-End Flow)

```
User Browser
     │
     │  1. POST /courses/fetch (NID + password)
     │◄─── Returns list of incomplete courses with prices
     │
     │  2. User selects courses
     │
     │  3. GET /payments/qr?amount=N  or  GET /payments/{job_id}/qr
     │◄─── PNG image of PromptPay QR code
     │
     │  4. User pays, takes screenshot of slip
     │
     │  5. POST /jobs/   multipart: nid, pwd, courses, total_price, total_hours, slip
     │     ├── Check Celery worker alive
     │     ├── Validate NID checksum (13-digit algorithm)
     │     ├── Save slip image to ./uploads/slips/
     │     ├── Create Job (status=pending) + Payment record
     │     ├── AES-encrypt NID + pwd → store in Redis (TTL=30min)
     │     └── Dispatch run_automation.delay(job_id)
     │◄─── JobOut (id, status, logs)
     │
     │  6. POST /payments/{job_id}/verify
     │     ├── Try SlipOK API (verifies via Bank of Thailand)
     │     │     ├── Rejected → 422
     │     │     └── Approved → use SlipOK data
     │     ├── Fallback: OCR slip image
     │     ├── Check 1: amount matches
     │     ├── Check 2: recipient account last-4 matches
     │     ├── Check 3: reference not duplicate
     │     ├── Check 4: slip age ≤ 30 min
     │     ├── Check 5: bank in allowed list
     │     ├── Check 6: recipient name matches
     │     ├── If any fail → 422 with error details
     │     └── All pass → payment.verified=true, job.status=queued
     │         run_automation.delay(job_id) called again
     │◄─── PaymentOut
     │
     │  7. WebSocket /ws/jobs/{job_id}
     │     ┌─ snapshot: existing logs + current status
     │     │
     │     │  [Celery Worker runs in background]
     │     │  ├── login DSL portal (Playwright)
     │     │  ├── SSO to SET e-Learning
     │     │  │
     │     │  └── For each course:
     │     │      ├── Enroll (if not enrolled)
     │     │      ├── Fetch topics list
     │     │      ├── Mark each topic complete via API
     │     │      ├── Pre-test (submit once)
     │     │      ├── Post-test (Gemini AI + cache + rotation, max 3 attempts)
     │     │      ├── Exam (same)
     │     │      ├── Survey (select radio, submit, confirm)
     │     │      └── Download certificate PDF
     │     │          └── Save to ./uploads/certs/{job_id}/cert_{course_id}.pdf
     │     │
     │     │   Each step publishes log via Redis pub/sub → WebSocket → Browser
     │     └─ Final: type="done"  → WebSocket closes
     │
     │  8. GET /jobs/{job_id}/certificates
     │◄─── List of certificates with download URLs
     │
     │  9. GET /jobs/{job_id}/certificates/bundle
     │◄─── Single PDF with all certificates merged
```

---

## Key Design Decisions

| Decision | Rationale |
|---|---|
| API-first course completion (no video playback) | SET e-Learning accepts direct API calls to mark topics complete; this is 100× faster than watching videos at 16× speed |
| AES-GCM credentials in Redis with 30-min TTL | Never persist raw credentials to disk; worker has a time-boxed window to use them |
| SHA-256 NID hash in DB | Allows detecting duplicate submissions without storing reversible PII |
| Celery `task_acks_late = True` | If the worker crashes mid-task, the job is re-queued instead of silently lost |
| `worker_prefetch_multiplier = 1` | Each Playwright instance is resource-intensive; serial processing avoids overload |
| Fresh asyncio loop per Celery task | Playwright's internal state can conflict between tasks if the event loop is reused |
| SlipOK API as primary verifier | SlipOK verifies directly against Bank of Thailand's PromptPay system — far more reliable than OCR |
| Max 3 exam attempts | SET anti-cheat policy disables certificate issuance if too many submissions are detected |
| Answer cache at `/tmp/exam_answer_cache.json` | Correct answers persist across jobs on the same worker, improving pass rate over time |
