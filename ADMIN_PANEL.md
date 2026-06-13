# Admin Panel — แผงผู้ดูแลระบบ dsl-auto

หน้า admin แยกต่างหากสำหรับผู้ดูแลระบบ (เห็นเฉพาะ `is_admin`) — ดูภาพรวม, จัดการงาน,
คลังคำตอบ, ผู้ใช้, การเงิน และเปิด/ปิด FREE_MODE สำหรับลูกค้าได้สด

> อัปเดตล่าสุด: 2026-06-13

---

## 1. เข้าใช้งาน

| | |
|---|---|
| URL หน้า admin | `/admin-panel` |
| เข้าผ่านหน้าลูกค้า | login บัญชี admin ที่ `/` → กดปุ่ม **"แผงแอดมิน"** มุมขวาบน (โผล่เฉพาะ admin) |
| สิทธิ์ | เฉพาะ User ที่ `is_admin = true` (เช็คทั้งฝั่ง frontend และ server) |

**บัญชี admin (dev/test):** `admin@dsl.local` / `admin12345678`

### ตั้งบัญชีเป็น admin
```bash
python scripts/make_admin.py <email>            # ตั้ง user ที่มีอยู่แล้วเป็น admin
python scripts/make_admin.py <email> <password> # สร้าง admin ใหม่ (ถ้ายังไม่มี user)
```

---

## 2. โครงสร้าง (ไฟล์ที่เกี่ยวข้อง)

| ไฟล์ | หน้าที่ |
|---|---|
| `frontend/admin.html` | หน้า admin (SPA, Tailwind) — login + 6 เมนู |
| `app/api/admin_panel.py` | API ของหน้า admin (JWT-gated ด้วย `get_current_admin`) |
| `app/api/admin.py` | (ของเดิม) endpoints แบบ HTTP Basic — ยังคงอยู่ ไม่เกี่ยวกัน |
| `app/utils/runtime_settings.py` | get/set ค่า runtime (FREE_MODE) ผ่าน Redis |
| `scripts/make_admin.py` | ตั้ง/สร้างบัญชี admin |
| `app/main.py` | mount `admin_panel.router` + serve `/admin-panel` |

**Auth:** ใช้ JWT เดียวกับลูกค้า (`/auth/login`). `get_current_admin` = `get_current_user` + เช็ค `is_admin`
(ไม่ใช่ → **403**). หน้า admin เก็บ token ใน `localStorage['dsl_admin_token']`

---

## 3. เมนูและฟีเจอร์

### 📊 ภาพรวม (Dashboard)
- การ์ดสถิติ: งานทั้งหมด/วันนี้, อัตราสำเร็จ %, วุฒิบัตร, รายได้ (จาก payment ที่ verified)
- กราฟแท่ง: งานแยกตามสถานะ (pending/queued/running/done/failed)
- สถานะระบบสด: Celery workers, ขนาด answer bank, คิวงานค้าง, FREE_MODE, ราคา/ชม.

### 🗂️ งานทั้งหมด (Jobs)
- ตารางงาน + ค้นหา (NID hash / อีเมล / job id) + กรองตามสถานะ
- ปุ่ม: ดาวน์โหลด cert (bundle), retry (งาน failed/pending), ลบ

### 📜 Log การทำงาน (realtime)
- เลือกงานจากรายการ → ดู log สด ผ่าน WebSocket `/ws/jobs/{id}` (snapshot ประวัติ + สตรีมสด)
- console สีตามชนิด log (sys/ok/play/warn/err/done) + progress bar + badge "● สด"
- ปุ่ม **log** ในตาราง "งานทั้งหมด" กระโดดมาดูงานนั้นได้เลย

### 🚀 ใช้งานฟรี (Run Free) — แอดมินรันงานเอง
- กรอก NID + รหัสผ่าน DSL → กด **ดึงคอร์ส** (`/courses/fetch`) → เลือกคอร์ส → **เริ่มงานฟรี**
- **ฟรีเสมอ ไม่ขึ้นกับ FREE_MODE global** — payment auto-verified (`"FREE"`), dispatch worker ทันที
- งานผูกกับบัญชี admin (ดูสถานะต่อใน "งานทั้งหมด")

### 🧠 คลังคำตอบ (Answer Bank)
- จำนวนเฉลยใน Redis + ตัวอย่าง + ปุ่มแนะนำคำสั่ง export

### 👥 ผู้ใช้งาน (Users)
- รายชื่อ user + จำนวนงาน + ตั้ง/ถอนสิทธิ์ admin

### 💳 การเงิน (Payments)
- รายการ payment + ยอด + เลขอ้างอิง + สถานะยืนยัน + ลิงก์ดูสลิป

### ⚙️ ตั้งค่าระบบ (Settings)
- **FREE_MODE toggle** (เปิด/ปิดได้สด) — ดูหัวข้อ 4
- **Worker control** — ปุ่ม เปิด/ปิด/รีสตาร์ท celery workers (รัน 4 ตัวขนานกัน) + badge สถานะออนไลน์
- แสดง ราคา/ชม., workers, ขนาด bank, สถานะ engine

---

## 4. FREE_MODE (เปิด/ปิดให้ลูกค้าใช้ฟรี)

แอดมินเปิด/ปิดได้จากหน้า **ตั้งค่าระบบ** → สวิตช์ **"FREE_MODE — ให้ลูกค้าใช้ฟรี"**
**มีผลทันที ไม่ต้อง restart**

**กลไก:** เก็บค่า override ใน Redis (`dsl:settings:free_mode` = `"1"`/`"0"`)
→ ถ้ายังไม่เคยตั้ง = ใช้ค่าจาก `.env` (`FREE_MODE`) เป็น default

| สถานะ | ผลกับลูกค้า |
|---|---|
| **เปิด** | ไม่ต้องจ่ายเงิน/แนบสลิป, ราคา 0, payment auto-verified, dispatch worker ทันที |
| **ปิด** | เก็บเงินตามปกติ (ต้องแนบสลิป + verify ผ่าน SlipOK) |

**จุดที่อ่านค่า runtime:** `app/api/jobs.py` (สร้างงาน), `app/api/payments.py` (`/info`),
`app/main.py` (`/health`), `app/api/admin_panel.py` (`/overview`)
ทั้งหมดเรียก `await get_free_mode()` แทน `settings.free_mode`

### API
| Method | Path | คืน |
|---|---|---|
| GET | `/admin/panel/free-mode` | `{"free_mode": bool}` |
| POST | `/admin/panel/free-mode` | body `{"on": true/false}` → `{"free_mode": bool}` |

---

## 5. API endpoints (admin_panel.py) — ทั้งหมด JWT admin-gated

| Method | Path | หน้าที่ |
|---|---|---|
| GET | `/admin/overview` | สถิติ dashboard + สถานะระบบ |
| GET | `/admin/panel/jobs?status=&q=&limit=` | รายการงาน (กรอง/ค้นหา) |
| POST | `/admin/panel/jobs/{id}/retry` | ส่งงานเข้า queue ใหม่ |
| POST | `/admin/panel/run-free` | แอดมินสร้างงานฟรี (body `{nid,pwd,courses[],total_hours}`) — ฟรีเสมอ, dispatch ทันที |
| DELETE | `/admin/panel/jobs/{id}` | ลบงาน + log + cert + payment |
| GET | `/admin/panel/users` | รายชื่อ user + จำนวนงาน |
| POST | `/admin/panel/users/{id}/toggle-admin` | ตั้ง/ถอน admin |
| GET | `/admin/panel/payments` | รายการ payment |
| GET | `/admin/panel/bank` | ขนาด + ตัวอย่าง answer bank |
| GET | `/admin/panel/free-mode` | ค่า FREE_MODE ปัจจุบัน |
| POST | `/admin/panel/free-mode` | เปิด/ปิด FREE_MODE |
| GET | `/admin/panel/workers` | จำนวน worker ออนไลน์ |
| POST | `/admin/panel/workers/start` | เปิด workers 4 ตัว (`scripts/start_workers.sh`) |
| POST | `/admin/panel/workers/stop` | ปิด workers ทั้งหมด (`scripts/stop_workers.sh`) |
| POST | `/admin/panel/workers/restart` | รีสตาร์ท workers (`scripts/restart_workers.sh`) |

---

## 6. ความปลอดภัย
- ทุก endpoint เช็ค `is_admin` ฝั่ง server → ลูกค้าทั่วไปยิง API ตรงก็ได้ **403**
- หน้า admin ไม่ใช่แค่ "ซ่อน" — ถ้าไม่ใช่ admin จะ login เข้าหน้า admin ไม่ได้ (เด้งออก)
- ปุ่ม "แผงแอดมิน" ในหน้าลูกค้าโผล่เฉพาะ admin (เช็คจาก `/auth/me`)

---

## 7. รันเพื่อทดสอบ (local)
```bash
# ต้องมี Postgres + Redis (docker-compose up -d postgres redis)
PYTHONPATH=. python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
# เปิด http://127.0.0.1:8001/admin-panel
```

## 8. TODO / ต่อยอด
- [ ] หน้าลูกค้า: ตอน FREE_MODE เปิด ให้ซ่อนขั้นจ่ายเงิน + ปุ่ม "เริ่มฟรี" (ตอนนี้ backend รับ no-slip แล้ว แต่ UI ลูกค้ายังโชว์ขั้นจ่าย)
- [ ] toggle ราคา/ชม. และ LLM provider จากหน้าเว็บ (ตอนนี้ตั้งใน `.env`)
