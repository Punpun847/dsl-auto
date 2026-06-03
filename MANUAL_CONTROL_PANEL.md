# Control Panel — คู่มือการใช้งาน

> Visual Pipeline App สำหรับควบคุมระบบ gyso ทั้งหมดในที่เดียว
> เปิดที่ `http://localhost:9100`

---

## สารบัญ

1. [Control Panel คืออะไร](#1-control-panel-คืออะไร)
2. [วิธีเปิดและปิด](#2-วิธีเปิดและปิด)
3. [ภาพรวม Layout](#3-ภาพรวม-layout)
4. [Top Bar — ปุ่มหลัก](#4-top-bar--ปุ่มหลัก)
5. [Node ทั้ง 9 ตัว — รายละเอียด](#5-node-ทั้ง-9-ตัว--รายละเอียด)
6. [Workflow ใช้งานปกติ](#6-workflow-ใช้งานปกติ)
7. [Confirmation Modal](#7-confirmation-modal)
8. [Keyboard Shortcuts](#8-keyboard-shortcuts)
9. [Troubleshooting](#9-troubleshooting)
10. [ความแตกต่างจาก Dashboard เดิม](#10-ความแตกต่างจาก-dashboard-เดิม)

---

## 1. Control Panel คืออะไร

แอป **ควบคุมระบบ gyso ทั้งหมดผ่านหน้าจอเดียว** โดยไม่ต้องเปิด PowerShell หลายตัวและจำคำสั่งยาวๆ

แสดงระบบเป็น **pipeline ภาพ** (ท่อน้ำ ▶ ต่อกัน) ของ component 9 ตัว ตั้งแต่ source (accounts.csv) ไปจนถึง output (merged PDF) — คลิก node ดูรายละเอียดและกดควบคุม

**สิ่งที่ทำได้:**
- 🟢 ดูสถานะ Docker, API, Redis, Workers, DB แบบ real-time (refresh ทุก 5s)
- ▶ เปิด/ปิดระบบทั้งหมดด้วยคลิกเดียว (`Start All` / `Stop All`)
- 📤 ส่งงาน (Submit) ทั้งไฟล์หรือ user เดียว
- 📑 Merge PDF
- 🔧 กู้ task ที่ติด (Fix Unacked)
- 📋 เช็ค courses ที่ user ทำได้ก่อน submit
- 👀 ดู log activity ของ workers

**สิ่งที่ไม่ทำ** (ใช้ Dashboard เดิม):
- ดู progress รายคอร์ส / job รายตัว → ไปที่ [http://localhost:9000](http://localhost:9000)
- ตอบ human exam → ไปที่ Dashboard เช่นกัน (จะมี notification)

---

## 2. วิธีเปิดและปิด

### เปิดครั้งแรก

```powershell
cd "D:\terminter01\gyso-backend-main (4)\gyso-backend-main"
.venv\Scripts\python.exe scripts\control_panel.py
```

จะเห็น log:
```
🎛️  Control Panel: http://localhost:9100
📊 Dashboard:      http://localhost:9000
⚙️  API:            http://127.0.0.1:8000
🐍 Python:         D:\...\python.exe
📂 Project root:   D:\...\gyso-backend-main
```

เปิดเบราว์เซอร์ → `http://localhost:9100`

### ปิด

กด `Ctrl+C` ใน terminal ที่รัน control_panel.py — หรือถ้าหา process ไม่เจอ:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*control_panel.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

> **หมายเหตุ:** Control Panel ไม่กระทบ workers หรือ jobs ที่กำลังรัน — ปิดได้ทุกเมื่อ

---

## 3. ภาพรวม Layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│  🎛️ GYSO Control Panel                                                  │
│  [▶ Start All] [⏹ Stop All] [📊 Dashboard] [📘 API docs] [🔄] ⏱ 14:23:01 │
├─────────────────────────────────────────────────────────────────────────┤
│  สีไฟ: 🟢 up   🔵 busy   🟡 warn   🔴 down   ⚪ unknown                  │
├─────────────────────────────────────────────────────────────────────────┤
│  ┌─────┐  ┌────┐  ┌────┐  ┌─────┐  ┌────┐  ┌────┐  ┌────┐  ┌────┐ ┌──┐ │
│  │📁   │▶│🚀  │▶│⚙️  │▶│📨   │▶│👷  │▶│🌐  │▶│🗄️  │▶│📑  │ │🐳│ │
│  │acc..│ │subm│ │API │ │Redis│ │Wkr.│ │DSL │ │DB  │ │Merg│ │Dk│ │
│  └─────┘  └────┘  └────┘  └─────┘  └────┘  └────┘  └────┘  └────┘ └──┘ │
├─────────────────────────────────────────────────────────────────────────┤
│  (เมื่อคลิก node → panel ขยายลงมาที่นี่)                                │
└─────────────────────────────────────────────────────────────────────────┘
```

**สีจุดบน node:**
| สี | ความหมาย |
|---|---|
| 🟢 เขียว | up — ปกติ |
| 🔵 น้ำเงิน | busy — มีงานในคิว |
| 🟡 เหลือง | warn — มีปัญหาบางส่วน (เช่น 2/4 workers) |
| 🔴 แดง | down — ไม่ทำงาน (กระพริบ) |
| ⚪ เทา | unknown — ตรวจไม่ได้ |

---

## 4. Top Bar — ปุ่มหลัก

### ▶ Start All
เปิดระบบทั้งหมด **เรียงตามลำดับ:**
1. `docker compose up -d` (postgres + redis)
2. รอ 3 วินาที
3. `uvicorn` (API port 8000)
4. รอ 2 วินาที
5. 4 Celery workers (`--pool=solo`)
6. รอ 2 วินาที
7. `dashboard.py` (port 9000)

ใช้เวลาประมาณ 10-15 วินาที — รอจน node ทุกตัวเป็นเขียวก่อน submit งาน

### ⏹ Stop All
- Kill python processes (celery, uvicorn, dashboard.py)
- `docker compose down`

> ⚠️ **งานที่กำลังรันจะถูก interrupt** — job status จะเป็น `running` ค้างใน DB
> ถ้าเกิดติด ใช้ `_reset_job.py <JOB_ID>` หลังเปิดระบบใหม่

### 📊 Dashboard
เปิด Dashboard เดิม (port 9000) ในแท็บใหม่ — สำหรับดู progress รายคอร์ส, ตอบ human exam

### 📘 API docs
เปิด OpenAPI docs (`/docs`) ของ FastAPI ในแท็บใหม่

### 🔄 Refresh
ดึง status ใหม่ทันที + rebuild panel ที่เปิดอยู่ (input ที่พิมไว้จะถูก preserve)

### ⏱ Timestamp + dot กระพริบ
แสดงเวลา last update — refresh อัตโนมัติทุก 5 วินาที

---

## 5. Node ทั้ง 9 ตัว — รายละเอียด

### 5.1 📁 accounts.csv

**stat บน node:** `8 rows (5 ok)` — จำนวน user ทั้งหมด / กี่คนมีชั่วโมง

**คลิก → panel แสดง:**
- 3 cards: Rows / มีชั่วโมง / รวมชั่วโมง
- ตาราง 6 แถวแรก (NID มาส์ก + ชั่วโมง)
- ข้อความ "📂 path: accounts.csv — แก้ไฟล์ตรงๆ ที่ project root"

**ทำอะไรได้:** ไม่มีปุ่ม — แก้ไฟล์ด้วย Notepad/VSCode แล้ว Refresh

**🟡 warn เมื่อ:** มี user บางคน column 3 (ชั่วโมง) ว่าง — จะถูกข้ามตอน submit

---

### 5.2 🚀 Submit Job

**stat บน node:** `พร้อมส่ง` / `accounts.csv ว่าง` / `API down`

**คลิก → panel แสดง:**
- ปุ่ม `📤 Submit accounts.csv ทั้งไฟล์` (background — รัน smart_submit.py)
- ฟอร์ม submit user เดียว:
  - NID (13 หลัก)
  - Password
  - Hours (default 18)
  - ปุ่ม `📤 Submit คนเดียว`
  - ปุ่ม `📋 ดู courses ที่ทำได้ก่อน` (รัน _list_incomplete.py — ไม่ submit)
- กล่อง output (โชว์ผลลัพธ์หลังกด)

**Submit accounts.csv:**
- รัน background — log ที่ `smart_submit.log`
- ใช้เวลานาน (login ทีละ user → fetch_courses → submit)

**Submit คนเดียว:**
- รัน foreground — รอ result ในหน้าเลย
- ใช้เวลา 1-3 นาที (login + fetch + submit)
- มี confirmation modal ก่อนรัน

**📋 ดู courses ก่อน:**
- ไม่ submit — แค่แสดงรายชื่อ courses ที่ user ยังไม่ผ่าน
- ใช้ก่อน submit เพื่อตรวจสอบว่ามี course เพียงพอมั้ย

**🔴 down เมื่อ:** API ไม่ทำงาน

---

### 5.3 ⚙️ API (uvicorn :8000)

**stat บน node:** `🟢 UP` / error type

**คลิก → panel แสดง:**
- 3 cards: Status / HTTP code / URL
- ปุ่ม `▶ Start` (เริ่ม uvicorn ใหม่)
- Link `📘 OpenAPI docs`

**🔴 down เมื่อ:** uvicorn ไม่รัน หรือ port 8000 ถูกบล็อก
**🟡 warn เมื่อ:** HTTP code ไม่ใช่ 200

---

### 5.4 📨 Redis Queue

**stat บน node:** `Q: 3 / U: 0` — Queue / Unacked

**คลิก → panel แสดง:**
- 2 cards: Queue (celery) / Unacked
- คำอธิบาย: "ถ้า unacked > 0 แสดงว่ามี task ติด — รัน Fix unacked เพื่อกู้"
- ปุ่ม `🔧 Fix Unacked` (รัน `_fix_unacked.py`)

**🔵 busy เมื่อ:** มี task ในคิว (รอ worker หยิบ)
**🟡 warn เมื่อ:** มี unacked > 0 (task หาย, ต้อง Fix)
**🔴 down เมื่อ:** Redis container ไม่รัน

---

### 5.5 👷 Workers 1-4

**stat บน node:** `4/4` หรือ `2/4` — running / total

**คลิก → panel แสดง:**
- Card "Running": แสดง 4/4 (เขียว) / 2/4 (เหลือง) / 0/4 (แดง)
- การ์ดของแต่ละ worker (1-4):
  - 👷 worker N
  - ● running หรือ ○ down
  - บรรทัด log ล่าสุด
  - "log X ago" (เก่ากี่นาที/ชั่วโมง)
- ปุ่ม `▶ Start 4 Workers` (เปิดทั้ง 4 ตัวพร้อมกัน)
- ปุ่ม `⏹ Stop All` (kill ทั้งหมด)

**🟢 up เมื่อ:** 4/4 running
**🟡 warn เมื่อ:** บางตัวล่ม (เช่น 3/4)
**🔴 down เมื่อ:** 0/4 — ระบบทำงานไม่ได้

> **หมายเหตุ:** Workers ต้องใช้ `--pool=solo` บน Windows เสมอ — Control Panel ใช้ flag นี้ให้อัตโนมัติ

---

### 5.6 🌐 DSL → SET (browser activity)

**stat บน node:** `3 active` / `🙋 รอตอบ 2` / `idle`

**คลิก → panel แสดง:**
- 3 บรรทัด log ล่าสุดที่มี emoji status ของ **แต่ละ worker** (1-4)
- ตัวอย่าง log:
  - `✅ post-test: ผ่าน (5/5 = 100%)`
  - `✅ cert saved: cert_1941.pdf`
  - `⚠️ exam: best 5/10 = 50% — ยังไม่ผ่าน 70%`
- ถ้ามี human ต้องตอบ → ข้อความเชื่อมไป Dashboard

**🟡 warn เมื่อ:** มี human exam รอตอบ → **ต้องไป Dashboard ตอบ**
**⚪ unknown เมื่อ:** ไม่มี emoji log (workers พึ่งเริ่ม)

---

### 5.7 🗄️ DB (PostgreSQL)

**stat บน node:** `12 jobs (1h)`

**คลิก → panel แสดง:**
- 4 cards: Jobs (1h) / Running / Queued / Done วันนี้
- ตาราง 5 jobs ล่าสุด: ID / status / hours / created
- ปุ่ม `📊 ดู Dashboard เต็ม` → ไปที่ port 9000 (เห็น progress รายคอร์ส)

**🔴 down เมื่อ:** Postgres ไม่ตอบสนอง (Docker ไม่รัน หรือ credentials ผิด)

---

### 5.8 📑 Merge PDF

**stat บน node:** `21 PDFs`

**คลิก → panel แสดง:**
- Card "Merged PDFs": จำนวนไฟล์ใน `certs/`
- ตารางไฟล์ล่าสุด 6 ตัว: ชื่อไฟล์ / ขนาด / เวลา
- ฟอร์ม merge:
  - NID (13 หลัก)
  - Days (default 7)
  - ปุ่ม `📑 Merge ตอนนี้`
- กล่อง output

**Merge:**
- เรียก `merge_new_certs.py <NID> --days <N>`
- Output อยู่ที่ `certs/<NID>.pdf` หรือ `certs/<NID>_xxx.pdf`
- ใช้เวลา ~10-30 วินาที

> ใช้ `--days` ให้ครอบคลุมทุก cert ที่ต้องการ — ถ้า user มี cert จากหลายวัน

---

### 5.9 🐳 Docker

**stat บน node:** `pg rd` (postgres + redis ทำงาน) / `down`

**คลิก → panel แสดง:**
- 2 cards: postgres / redis (● up / ○ down)
- ตาราง containers ทั้งหมด: ชื่อ / image / status
- ปุ่ม `▶ Start` (`docker compose up -d`)
- ปุ่ม `⏹ Stop` (`docker compose down`)

**🟢 up เมื่อ:** postgres + redis ทั้งคู่ run
**🟡 warn เมื่อ:** มีตัวใดตัวหนึ่ง
**🔴 down เมื่อ:** Docker daemon ไม่รัน หรือไม่มี containers

> Docker เป็น node ลอย (ไม่อยู่ในเส้น pipeline) เพราะเป็น dependency พื้นฐาน — ไม่ได้รับ input จาก node อื่น

---

## 6. Workflow ใช้งานปกติ

### 🌅 เริ่มวัน

1. เปิด control_panel.py → `http://localhost:9100`
2. ดูว่า node ไหนเทา/แดงบ้าง
3. ถ้าระบบยังไม่เปิด → คลิก **▶ Start All** บน topbar
4. รอ 10-15 วินาที จน node ทุกตัวเขียว
5. ตรวจ accounts.csv (คลิก node 📁) — แน่ใจว่ามีข้อมูล user

### 📤 ส่งงาน batch

1. แน่ใจว่า accounts.csv ครบทุก column (NID, PWD, Hours)
2. คลิก node 🚀 Submit
3. คลิก **📤 Submit accounts.csv ทั้งไฟล์**
4. ยืนยันใน modal
5. งานจะรัน background → log ที่ `smart_submit.log`
6. ไปดูที่ Dashboard (port 9000) เพื่อดู progress

### 📤 ส่งงาน user เดียว

1. คลิก node 🚀 Submit
2. กรอก NID + PWD + Hours
3. (แนะนำ) คลิก **📋 ดู courses ที่ทำได้ก่อน** ก่อน
4. ถ้า courses มีพอ → คลิก **📤 Submit คนเดียว**
5. ยืนยันใน modal → รอ result ในหน้า

### 📑 Merge PDF

1. รอจน job status = done (ดูที่ DB node หรือ Dashboard)
2. คลิก node 📑 Merge PDF
3. กรอก NID + Days (จำนวนวันย้อนหลัง)
4. คลิก **📑 Merge ตอนนี้**
5. รอ ~10-30 วินาที → ดู output
6. ไฟล์อยู่ที่ `certs/<NID>.pdf`

### 🌃 จบวัน

1. ตรวจว่าไม่มี job รัน (node 🗄️ DB → Running = 0)
2. คลิก **⏹ Stop All** บน topbar
3. ยืนยันใน modal
4. ปิด Control Panel ด้วย Ctrl+C

---

## 7. Confirmation Modal

ทุก action ที่**ไม่ใช่ read-only** จะแสดง modal ก่อนรัน

```
┌─────────────────────────────────────┐
│  ⚠️ ยืนยัน                          │
│                                     │
│  คำอธิบายว่าจะทำอะไร                 │
│  + ผลข้างเคียงที่อาจเกิด             │
│                                     │
│              [ยกเลิก] [ยืนยัน]      │
└─────────────────────────────────────┘
```

| ปุ่มที่ต้อง confirm | ปุ่มที่ไม่ต้อง confirm |
|---|---|
| ▶ Start All | 📊 Dashboard (เปิดลิงก์) |
| ⏹ Stop All | 📘 API docs |
| ▶ Start API/Workers/Docker | 🔄 Refresh |
| ⏹ Stop Workers/Docker | 📋 ดู courses ที่ทำได้ |
| 📤 Submit (CSV / คนเดียว) | 📑 Merge PDF (ของแค่ user เดียว) |
| 🔧 Fix Unacked | |

> เหตุผล: ระบบ gyso มี user จริงใช้งาน — กัน misclick

---

## 8. Keyboard Shortcuts

| ปุ่ม | ผล |
|---|---|
| `Esc` (โหมด modal) | ปิด modal (ยกเลิก) |
| `Esc` (โหมดอ่าน panel) | ปิด panel ทั้งหมดที่เปิดอยู่ |
| `F5` | Refresh เต็มหน้า (ค่า input ในฟอร์มจะหายเพราะ browser reload) |

> **อย่ากด F5** ตอนกำลังกรอกฟอร์ม — ใช้ปุ่ม 🔄 Refresh แทน (ค่า input ถูกเก็บไว้)

---

## 9. Troubleshooting

### ❌ เปิด `http://localhost:9100` แล้วโหลดไม่ได้

```powershell
# 1. ตรวจว่า port 9100 ใครใช้
Get-NetTCPConnection -LocalPort 9100 -ErrorAction SilentlyContinue

# 2. ดู process control_panel.py
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*control_panel.py*' } | Select-Object ProcessId,CommandLine

# 3. ถ้ามีหลายตัวรันค้าง → kill ทั้งหมด
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*control_panel.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

# 4. เริ่มใหม่
.venv\Scripts\python.exe scripts\control_panel.py
```

### ❌ Node เทาทุกตัว (unknown)

หมายความว่า `/api/status` error
- เปิด Browser DevTools (F12) → Console → ดู error
- มักเป็น Python error → ดู terminal ที่รัน control_panel.py

### ❌ คลิก ▶ Start All แล้ว node ยังแดง

- รอเพิ่ม 10-15 วินาที — บางตัว start ช้า
- ดู log ใน terminal — มี error?
- ลอง Start ทีละตัวจาก panel ของ node นั้นๆ

### ❌ Submit คนเดียวค้างนาน

- foreground call ใช้เวลา 1-3 นาที (login + fetch_courses + submit)
- ถ้า > 5 นาที → timeout
- ดู error ในกล่อง output

### ❌ ฟอร์มที่พิมหาย

> **fixed แล้ว 2026-05-29** — ค่า input ถูก preserve ข้าม refresh
> ถ้ายังเจอ → restart control_panel.py + refresh browser (Ctrl+Shift+R)

### ❌ ฟอร์ม submit คนเดียวรันไม่ขึ้น

- ตรวจว่า NID 13 หลัก, password ไม่ว่าง, hours เป็นตัวเลข
- ดู toast error ขวาล่าง

### ❌ Action สำเร็จแต่ node ไม่เปลี่ยนสี

- คลิก 🔄 Refresh เพื่อ force update
- หรือรอ 5 วินาทีรอบ auto-refresh

---

## 10. ความแตกต่างจาก Dashboard เดิม

| Feature | Control Panel (9100) | Dashboard (9000) |
|---|---|---|
| **วัตถุประสงค์** | ควบคุมระบบ | Monitor jobs |
| **เห็นทุก component** | ✅ pipeline 9 nodes | ❌ เน้น jobs |
| **เปิด/ปิด service** | ✅ มีปุ่ม | ❌ ไม่มี |
| **Submit job ผ่าน UI** | ✅ มีฟอร์ม | ❌ ไม่มี |
| **Merge PDF ผ่าน UI** | ✅ มีฟอร์ม | ✅ มี (per job) |
| **ดู job รายคอร์ส + progress bar** | ❌ มีแค่ summary | ✅ เต็ม |
| **ตอบ human exam** | ❌ ลิงก์ไป Dashboard | ✅ มี radio button |
| **ดู cert PDF รายไฟล์** | ❌ ลิงก์ไป Dashboard | ✅ มี |
| **Live activity log** | ✅ 3 บรรทัด/worker | ❌ มีแต่ latest log line |

**สรุป:** ใช้คู่กัน — Control Panel เป็น "เครื่องบินคอนโทรล", Dashboard เป็น "เครื่องวัด"

---

## ภาคผนวก: Endpoints ของ Control Panel API

| Method | Path | ทำอะไร |
|---|---|---|
| GET | `/` | หน้า HTML หลัก |
| GET | `/api/status` | คืน JSON ของ status ทุก node |
| POST | `/start/all` | เปิดระบบทั้งหมด |
| POST | `/start/docker` | docker compose up |
| POST | `/start/api` | เปิด uvicorn |
| POST | `/start/workers` | เปิด 4 workers |
| POST | `/start/dashboard` | เปิด dashboard.py |
| POST | `/stop/all` | หยุดทุกอย่าง + docker compose down |
| POST | `/stop/workers` | kill workers |
| POST | `/stop/docker` | docker compose down |
| POST | `/submit/csv` | smart_submit.py background |
| POST | `/submit/one` | _submit_one.py (form: nid, pwd, hours) |
| POST | `/merge` | merge_new_certs.py (form: nid, days) |
| POST | `/fix/unacked` | _fix_unacked.py |
| POST | `/list_incomplete` | _list_incomplete.py (form: nid, pwd) |

**Response:** ทุก POST คืน JSON `{ok: bool, stdout: str, stderr: str, code: int}`

---

## ภาคผนวก: Environment Variables

อ่านจาก `.env` ใน project root (ใช้ python-dotenv)

| Variable | Default | คำอธิบาย |
|---|---|---|
| `CONTROL_PANEL_PORT` | `9100` | port ของ control panel |
| `DASHBOARD_PORT` | `9000` | port ของ dashboard เดิม (สำหรับ link) |
| `DATABASE_URL` | `postgresql://gyso@localhost:5432/gyso_db` | DB connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
