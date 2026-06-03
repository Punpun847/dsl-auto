# คู่มือการใช้งานระบบ GYSO Automation

> ระบบนี้ทำ e-learning กยศ. (DSL) บน SET อัตโนมัติ — login, ทำแบบทดสอบ, download ใบประกาศ, และ merge PDF รวมเล่ม

---

## สารบัญ

1. [ภาพรวมระบบ](#1-ภาพรวมระบบ)
2. [สิ่งที่ต้องมีก่อนใช้งาน](#2-สิ่งที่ต้องมีก่อนใช้งาน)
3. [วิธีเปิดระบบ (Start Services)](#3-วิธีเปิดระบบ-start-services)
4. [วิธีส่งงาน (Submit Jobs)](#4-วิธีส่งงาน-submit-jobs)
5. [การ Monitor ความคืบหน้า](#5-การ-monitor-ความคืบหน้า)
6. [การ Merge PDF ใบประกาศ](#6-การ-merge-pdf-ใบประกาศ)
7. [วิธีปิดระบบ](#7-วิธีปิดระบบ)
8. [Troubleshooting ปัญหาที่พบบ่อย](#8-troubleshooting-ปัญหาที่พบบ่อย)
9. [ไฟล์สำคัญในโปรเจกต์](#9-ไฟล์สำคัญในโปรเจกต์)

---

## 1. ภาพรวมระบบ

```
accounts.csv
    │
    ▼
smart_submit.py  ──→  API (port 8000)  ──→  Redis Queue
                                                  │
                              ┌───────────────────┤
                              │   Celery Workers  │  (4 workers, --pool=solo)
                              │  worker1..worker4 │
                              └───────────────────┘
                                        │
                              Playwright Browser
                              (กยศ. DSL → SSO → SET)
                                        │
                              ┌─────────┴──────────┐
                              │  PostgreSQL (5432)  │
                              │  Redis (6379)       │
                              └────────────────────┘
                                        │
                              merge_new_certs.py
                                        │
                              certs/<NID>_merged.pdf
```

**Flow การทำงาน:**
1. ใส่ข้อมูล user ใน `accounts.csv`
2. รัน `smart_submit.py` → login SET ดึง incomplete courses → ส่ง job ผ่าน API
3. Celery worker รับ job → เปิด browser → login DSL → SSO → SET → ทำทุกคอร์ส
4. แต่ละคอร์ส: pre-test → video → post-test (LLM) → exam (LLM) → survey → ดาวน์โหลด cert
5. เมื่อ job `done` → merge PDF รวมเป็นไฟล์เดียว

---

## 2. สิ่งที่ต้องมีก่อนใช้งาน

### Services ที่ต้องรัน
- **Docker Desktop** — สำหรับ PostgreSQL + Redis
- **Python venv** — ที่ `.venv/` (Python 3.12)

### ไฟล์ที่ต้องมี
```
accounts.csv        ← รายชื่อ user (NID,PWD ต่อบรรทัด)
```

รูปแบบ `accounts.csv`:
```
1234567890123,password1,15
9876543210987,password2,18
1111111111111,password3,12
```

> **บังคับใส่ column 3 (ชั่วโมง) ทุกแถว** — ถ้าไม่มีจะถูกข้ามและไม่ submit
> `MAX_HOURS` คำนวณอัตโนมัติ = target + 1 (เช่น เป้า 15 → cap 16)

### ตรวจสอบก่อนเริ่ม
```powershell
# Docker ต้องรันอยู่
docker ps   # ควรเห็น postgres และ redis

# Venv ต้องมี
ls .venv\Scripts\python.exe
```

---

## 3. วิธีเปิดระบบ (Start Services)

> **สำคัญ:** ต้องทำตามลำดับนี้เสมอ — ห้าม start workers ก่อน Docker

### Step 1: เปิด Docker (PostgreSQL + Redis)
```powershell
docker compose up -d
```
ตรวจสอบ:
```powershell
docker ps   # ต้องเห็น gyso_postgres และ gyso_redis
```

### Step 2: เปิด API Server (uvicorn)
```powershell
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"
$env:PYTHONIOENCODING = "utf-8"
Start-Process -FilePath ".venv\Scripts\python.exe" `
    -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" `
    -WorkingDirectory (Get-Location) -WindowStyle Hidden
```

### Step 3: เปิด Celery Workers (4 ตัว)

> **ต้องใช้ `--pool=solo` เสมอ** บน Windows เพื่อป้องกัน OSError handle conflict

```powershell
$py = (Resolve-Path ".venv\Scripts\python.exe").Path
$wd = (Resolve-Path ".").Path

foreach ($n in 1,2,3,4) {
    Start-Process -FilePath $py `
        -ArgumentList "-m celery -A app.worker.celery_app worker --pool=solo -n worker$n@%h --logfile=celery$n.log --loglevel=info" `
        -WorkingDirectory $wd -WindowStyle Hidden
    Start-Sleep -Milliseconds 500
}
Write-Host "Workers started"
```

### Step 4: เปิด Dashboard
```powershell
Start-Process -FilePath $py -ArgumentList "scripts/dashboard.py" -WorkingDirectory $wd -WindowStyle Hidden
Start-Sleep -Seconds 3
try { $r = Invoke-WebRequest -Uri "http://localhost:9000" -TimeoutSec 3 -UseBasicParsing; Write-Host "Dashboard UP: $($r.StatusCode)" } catch { Write-Host "ยังไม่พร้อม: $_" }
```
เข้าดูได้ที่ `http://localhost:9000` — แสดง progress, status, cert count ของแต่ละ user (refresh อัตโนมัติทุก 5 วินาที)

### ตรวจสอบว่า workers พร้อม
```powershell
$env:PYTHONIOENCODING = "utf-8"
Start-Sleep -Seconds 8
.venv\Scripts\python.exe scripts\_tail_end.py celery1.log 4
# ต้องเห็น: worker1@faozia ready.
```

---

## 4. วิธีส่งงาน (Submit Jobs)

### วิธีที่ 1: ส่งทุก user ใน accounts.csv พร้อมกัน (แนะนำ)
```powershell
$env:PYTHONIOENCODING = "utf-8"
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"
.venv\Scripts\python.exe scripts\smart_submit.py accounts.csv
```

**สิ่งที่ script ทำ:**
- Login SET ทีละ user เพื่อดู incomplete courses (ไม่ซ้ำกับที่ทำไปแล้ว)
- เลือกคอร์สให้ครบ 18 ชั่วโมง (แต่ไม่เกิน 19 ชั่วโมง)
- ส่ง job ผ่าน API → Celery รับไปรัน
- บันทึก `smart_jobs.csv` (NID → job_id)

---

### วิธีที่ 2: ส่ง user คนเดียว
```powershell
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_submit_one.py <NID> <PWD> <HOURS>

# ตัวอย่าง:
.venv\Scripts\python.exe scripts\_submit_one.py 1570900116157 PH68002568 18
```

> **บังคับใส่ชั่วโมง** — ไม่มี default

---

### วิธีที่ 3: ดูรายการ courses ที่ทำได้ก่อน (ไม่ submit)
```powershell
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_list_incomplete.py <NID> <PWD>
```
จะแสดงรายชื่อคอร์สที่ยังไม่ได้ทำ พร้อมชั่วโมง — ใช้ตรวจสอบก่อนส่งจริง

---

### กฎสำคัญ
| กฎ | รายละเอียด |
|---|---|
| ชั่วโมงต่างกันต่อคน | column 3 ใน accounts.csv บังคับระบุ — ถ้าขาดจะข้าม user นั้น |
| cap อัตโนมัติ | `MAX_HOURS = target + 1` เช่น เป้า 15 → ไม่เกิน 16 |
| เลือกใหญ่ก่อน | `pick_courses()` เรียง desc — คอร์สชั่วโมงเยอะเลือกก่อน (ถ้าใหญ่เกิน cap ข้ามไม่ break) |
| ไม่ซ้ำ courses | `smart_submit.py` ดึงจาก SET live — courses ที่ทำไปแล้วถูกกรองออก |
| Payment ต้องมี | API สร้าง payment record อัตโนมัติตอน submit |

---

## 5. การ Monitor ความคืบหน้า

### Dashboard (แนะนำ)
```
http://localhost:9000
```
- Refresh ทุก 5 วินาทีอัตโนมัติ
- แสดง progress, status, cert count
- ดูได้เฉพาะ jobs ใน 2 ชั่วโมงล่าสุด

---

### ดู Log แบบ real-time
```powershell
$env:PYTHONIOENCODING = "utf-8"
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"

# ดู worker1 (ย้อนหลัง 20 บรรทัดล่าสุด)
.venv\Scripts\python.exe scripts\_tail_end.py celery1.log 20

# ดูตั้งแต่ timestamp ที่กำหนด
.venv\Scripts\python.exe scripts\_tail_log.py celery1.log "19:30:00"
```

**Log ที่สำคัญ:**
```
🚀 start browser          ← เริ่มทำงาน
✅ logged in               ← login DSL สำเร็จ
✅ SSO tab เปิดแล้ว        ← เข้า SET แล้ว
✅ post-test: ผ่าน 5/5     ← ผ่านแบบทดสอบ
✅ cert saved: cert_XXX.pdf ← ได้ใบประกาศ
🏁 job done               ← จบทั้งหมด
```

---

### ดูสถานะใน DB
```powershell
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_check_job.py
# (แก้ job_id ใน script ก่อน)
```

---

### ตรวจสถานะ workers
```powershell
Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*celery*worker*" } |
    Select-Object ProcessId, CommandLine
```

---

## 6. การ Merge PDF ใบประกาศ

### วิธีที่ 1: Auto-merger (อัตโนมัติ)
รัน `auto_merger.py` ทิ้งไว้ตลอดการทำงาน — มันตรวจทุก 30 วินาที พอ user ไหน status=done จะ merge ทันที:

```powershell
$env:PYTHONIOENCODING = "utf-8"
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"
.venv\Scripts\python.exe scripts\auto_merger.py
```

> หมายเหตุ: ต้องเพิ่มรายชื่อ user ใน `NAMES` dict ใน `auto_merger.py` ก่อน

---

### วิธีที่ 2: Merge manual ทีละคน
```powershell
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"   # ← สำคัญมาก! ต้องอยู่ใน project root
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\merge_new_certs.py <NID> --days 1
```

ผลลัพธ์จะอยู่ที่: `certs/<ชื่อ>_merged.pdf`

> **ข้อควรระวัง:** ต้องรันจาก project root เสมอ — ถ้ารันจากที่อื่น path ผิด

---

## 7. วิธีปิดระบบ

### ปิด Workers ก่อน (สำคัญ — ทำทุกครั้งก่อน restart)
```powershell
# Kill เฉพาะ Celery worker processes
Get-WmiObject Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*celery*worker*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Killed $($_.ProcessId)" }
```

### ปิดทุกอย่าง
```powershell
# Kill uvicorn, dashboard, workers ทั้งหมด
Get-Process python* | Stop-Process -Force
docker compose down
```

---

## 8. Troubleshooting ปัญหาที่พบบ่อย

---

### ❌ Job ค้างที่ `queued` ไม่ขยับ

**สาเหตุที่พบบ่อย:**
1. Workers ไม่ได้รัน หรือ crash
2. Redis queue ว่าง (task ติดใน unacked)
3. Status เป็น `running` โดย worker เก่าที่ crash

**วิธีแก้:**
```powershell
# 1. ตรวจ workers
Get-WmiObject Win32_Process | Where-Object { $_.CommandLine -like "*celery*worker*" } | Select-Object ProcessId

# 2. ดู log
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_tail_end.py celery1.log 10

# 3. ถ้า task ติดใน unacked
.venv\Scripts\python.exe scripts\_fix_unacked.py

# 4. ถ้า status=running แต่ไม่มีใครทำงาน → reset
.venv\Scripts\python.exe scripts\_reset_job.py <JOB_ID>
```

---

### ❌ OSError: [WinError 6] The handle is invalid

**สาเหตุ:** มี workers หลายชุดรันพร้อมกัน (pipe handle ชนกัน)

**วิธีแก้:**
```powershell
# Kill workers ทั้งหมด
Get-WmiObject Win32_Process |
    Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*celery*worker*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# รอสักครู่
Start-Sleep -Seconds 3

# ตรวจ/กู้ task ที่ค้าง
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_fix_unacked.py

# Start ใหม่ด้วย --pool=solo เสมอ
```

---

### ❌ ValueError: not enough values to unpack (expected 3, got 0)

**สาเหตุ:** Workers รันด้วย Python 3.14 (ระบบ) แทนที่จะเป็น venv Python 3.12

**วิธีแก้:**
```powershell
# Kill workers Python312/Python314 ทั้งหมด
# แล้ว start ใหม่โดยใช้ path venv เต็ม:
$py = (Resolve-Path ".venv\Scripts\python.exe").Path
```

---

### ❌ ModuleNotFoundError

**วิธีแก้:**
```powershell
.venv\Scripts\pip install <ชื่อ module> --only-binary=:all:
```

---

### ❌ Login ไม่ได้ / หน้าเว็บค้าง

**วิธีตรวจสอบ:**
```powershell
# ดู log ตอน login
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_tail_log.py celery1.log "19:30"
# ดูว่า popup ปิดได้มั้ย, NID/PWD ถูกมั้ย
```

---

### ❌ Dashboard ไม่แสดง jobs ที่เพิ่งทำ

**สาเหตุ:** Dashboard แสดงแค่ jobs ใน 2 ชั่วโมงล่าสุด

**วิธีแก้:** ดู DB โดยตรง:
```powershell
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_check_job.py
```

---

### ❌ Merge PDF ไม่มีใบใหม่

**สาเหตุ:** รัน `merge_new_certs.py` จาก directory ผิด

**วิธีแก้:**
```powershell
# ต้องอยู่ใน project root เสมอ!
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"
.venv\Scripts\python.exe scripts\merge_new_certs.py <NID> --days 1
```

---

### ❌ Dashboard แสดง Progress ไม่ครบ (เช่น 17/19) แม้ job status=done

**สาเหตุ:** Dashboard นับเฉพาะ cert ที่ `pdf_path IS NOT NULL` — บาง course ทำเสร็จแต่ download PDF ล้มเหลว (timeout/network กระตุก) ทำให้ cert record ใน DB มี `pdf_path = NULL`

> **หมายเหตุ:** `retry_pending_certs` task ที่มีอยู่ใน Celery beat **ทำงานไม่ได้** เพราะ Redis credentials ถูกลบหลัง job done ไปแล้ว

**วิธีตรวจสอบ:**
```powershell
$env:PYTHONIOENCODING = "utf-8"
$script = @'
from sqlalchemy import create_engine, text
engine = create_engine("postgresql://gyso:gyso1234@localhost:5432/gyso_db")
with engine.connect() as c:
    rows = c.execute(text(
        "SELECT j.id, j.status, COUNT(cert.id) as total, "
        "COUNT(cert.pdf_path) as with_pdf "
        "FROM jobs j LEFT JOIN certificates cert ON cert.job_id = j.id "
        "WHERE j.created_at > NOW() - INTERVAL '24 hours' "
        "GROUP BY j.id, j.status ORDER BY j.created_at DESC"
    )).fetchall()
    for r in rows:
        if r[2] != r[3]:
            print(f"MISSING PDF: {str(r[0])[:8]}  status={r[1]}  total={r[2]}  with_pdf={r[3]}")
'@
$script | .venv\Scripts\python.exe 2>&1
```

**วิธีแก้ — รัน repair script:**
```powershell
# 1. แก้ REPAIR_JOBS ใน scripts/_repair_certs.py ให้ตรงกับ job ที่มีปัญหา
# 2. รัน:
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\_repair_certs.py
```

`_repair_certs.py` จะ login → SSO → รัน course ใหม่ → อัปเดต `pdf_path` ใน DB อัตโนมัติ

---

### ❌ Exam ไม่ผ่าน — DeepSeek ตอบผิดและ cache ไม่มีคำตอบ

**สาเหตุ:** DeepSeek ถูกเรียกแค่ attempt 0 เท่านั้น — ถ้าผิดและ cache ไม่มีคำตอบสำหรับชุดคำถามที่ randomize มาใหม่ใน attempt 1-2 ระบบจะ **skip โดยไม่เดา** เพื่อป้องกัน anti-cheat → course ไม่จบ → ไม่ได้ cert

**วิธีแก้ (อัตโนมัติ):** ระบบจะแสดงคำถามที่ตอบไม่ได้ใน **Dashboard** (`http://localhost:9000`) ทันที พร้อม radio buttons ให้เลือกคำตอบเอง

```
Flow:
  DeepSeek/cache ตอบไม่ได้
        ↓
  Worker เขียนคำถาม → Redis (รอ 10 นาที)
        ↓
  Dashboard แสดง 🚨 รอคำตอบจากคุณ
        ↓
  กดเลือกคำตอบ → คลิก "ส่งคำตอบ"
        ↓
  Worker รับคำตอบ → submit → ทำ course ต่อ
```

> Dashboard จะ refresh เร็วขึ้นเป็น **3 วินาที** อัตโนมัติเมื่อมีคำถามรอ

**วิธีป้องกันระยะยาว:** ใส่ `CLAUDE_API_KEY` ใน `.env` เพื่อเป็น fallback เมื่อ DeepSeek ตอบผิด (Claude Haiku จะถูกเรียกใน attempt ถัดไป)

---

## 9. ไฟล์สำคัญในโปรเจกต์

| ไฟล์ | หน้าที่ |
|---|---|
| `accounts.csv` | รายชื่อ user (NID,PWD) |
| `scripts/smart_submit.py` | ส่งงาน batch ทุก user ใน accounts.csv |
| `scripts/_submit_one.py` | ส่งงาน user คนเดียว |
| `scripts/_list_incomplete.py` | ดู courses ที่ยังไม่ได้ทำ |
| `scripts/auto_merger.py` | Merge PDF อัตโนมัติเมื่อ status=done |
| `scripts/merge_new_certs.py` | Merge PDF manual ทีละคน |
| `scripts/dashboard.py` | Dashboard port 9000 |
| `scripts/_repair_certs.py` | Re-run course ที่ cert หาย (pdf_path=NULL) |
| `scripts/_fix_unacked.py` | กู้ task ที่ติดใน Redis unacked |
| `scripts/_reset_job.py` | Reset job status + re-dispatch |
| `scripts/_check_job.py` | ตรวจสถานะ job, payment, Redis |
| `scripts/_tail_end.py` | ดู N บรรทัดท้ายของ log |
| `scripts/_tail_log.py` | ดู log ตั้งแต่ timestamp |
| `celery1.log` ~ `celery4.log` | Log ของแต่ละ worker |
| `certs/` | PDF ใบประกาศที่ merge แล้ว |
| `uploads/certs/<job_id>/` | PDF รายคอร์สก่อน merge |
| `smart_jobs.csv` | ผลลัพธ์ NID → job_id หลัง smart_submit |

---

## Quick Reference

```powershell
# เปิดระบบครบ
docker compose up -d
$py = (Resolve-Path ".venv\Scripts\python.exe").Path; $wd = (Resolve-Path ".").Path
Start-Process -FilePath $py -ArgumentList "-m uvicorn app.main:app --host 127.0.0.1 --port 8000" -WorkingDirectory $wd -WindowStyle Hidden
foreach ($n in 1,2,3,4) { Start-Process -FilePath $py -ArgumentList "-m celery -A app.worker.celery_app worker --pool=solo -n worker$n@%h --logfile=celery$n.log --loglevel=info" -WorkingDirectory $wd -WindowStyle Hidden; Start-Sleep -Milliseconds 500 }

# ส่งงาน
$env:PYTHONIOENCODING = "utf-8"
.venv\Scripts\python.exe scripts\smart_submit.py accounts.csv

# ดู log
.venv\Scripts\python.exe scripts\_tail_end.py celery1.log 20

# Merge PDF
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"
.venv\Scripts\python.exe scripts\merge_new_certs.py <NID> --days 1

# Kill workers (ก่อน restart เสมอ)
Get-WmiObject Win32_Process | Where-Object { $_.Name -like "python*" -and $_.CommandLine -like "*celery*worker*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
