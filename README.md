# 🎓 DSL Auto (กู้ยืม กยศ. Automation Platform)

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.4-37814A?style=for-the-badge&logo=celery&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?style=for-the-badge&logo=redis&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.47-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)

> ⚡ ระบบอัตโนมัติครบวงจรสำหรับประมวลผลและเรียนเก็บชั่วโมงจิตอาสาบนพอร์ทัล SET e-Learning ผ่านการล็อกอินระบบกองทุนเงินให้กู้ยืมเพื่อการศึกษา (กยศ.) ด้วยสถาปัตยกรรม Asynchronous Queue, WebSocket Live Streaming และ AI Auto-Quiz Engine

---

## 🌟 ฟีเจอร์หลัก (Key Highlights)

- 🔐 **Zero-Storage PII Security:** ไม่เก็บเลขบัตรประชาชนหรือรหัสผ่านดิบในฐานข้อมูล เข้ารหัสด้วย AES-256-GCM บน Redis ชั่วคราว (TTL 30 นาที) และเก็บเพียง SHA-256 Hash
- ⚡ **API-Driven Course Completion:** เร่งสปีดการเก็บชั่วโมงผ่าน API ภายใน แทนการดูวิดีโอแบบจำลองความเร็ว ช่วยลดเวลาจากหลายชั่วโมงเหลือเพียงไม่กี่นาที
- 🧠 **Smart AI Quiz Solver:** กลยุทธ์ทำข้อสอบ 3 ชั้น (Persistent Answer Cache + DeepSeek AI + Option Fallback) พร้อมระบบป้องกัน Anti-Cheat ลิมิตไม่เกิน 3 ครั้ง
- 💳 **Automated Payment & Slip Verification:** ตรวจสลิปโอนเงินอัตโนมัติด้วย SlipOK API ร่วมกับ Fallback OCR (Pytesseract) ตรวจสอบบัญชีปลายทาง ยอดเงิน และเวลาโอน
- 📡 **Real-time Progress Streaming:** ส่ง Log การทำงานแบบสด ๆ เข้าสู่หน้าเว็บของผู้ใช้ผ่าน WebSocket และ Redis Pub/Sub
- 📑 **One-Click Certificate Bundler:** ดาวน์โหลดและรวมไฟล์ใบประกาศนียบัตร PDF ทุกวิชาเป็นไฟล์เดียวพร้อมยื่นสถานศึกษา

---

## 🏗️ Architecture & Tech Stack

```
User Frontend (Web) ──► FastAPI (ASGI API Gateway) ──► PostgreSQL (Metadata & Status)
       │                         │
       ├── WebSocket (Live Logs) ├── Redis (Broker / Cache / AES-GCM Credentials)
       │                         │
       └─────────────────────────┴──► Celery Worker (Playwright / Chromium Headless)
                                             │
                                             ├── DSL Portal (WSA Angular Login)
                                             ├── SET e-Learning (SSO & Course API)
                                             └── DeepSeek Chat (AI Exam Solver)
```

- **Backend:** FastAPI, Pydantic v2, SQLAlchemy 2.0 (Async + asyncpg)
- **Task Queue & Broker:** Celery, Redis
- **Database:** PostgreSQL 16
- **Browser Automation:** Playwright Chromium Headless
- **AI & OCR:** DeepSeek API, Pytesseract, SlipOK API
- **Security:** AES-256-GCM, bcrypt, JWT (python-jose)

---

## 📁 โครงสร้างโปรเจกต์

```
dsl-auto/
├── app/
│   ├── main.py              # FastAPI app & routing setup
│   ├── config.py            # Pydantic Settings (.env)
│   ├── database.py          # SQLAlchemy async session factory
│   ├── api/                 # Endpoints (jobs, payments, courses, auth, admin, ws)
│   ├── models/              # Database models (User, Job, Payment, Certificate, JobLog)
│   ├── schemas/             # Pydantic validation schemas
│   ├── utils/               # Security, OCR, SlipOK, LLM Answer, Logger
│   └── worker/              # Celery app, tasks, DSLClient automation engine
├── frontend/                # Web UI & Admin Dashboard
├── alembic/                 # Database migrations
├── docker-compose.yml       # PostgreSQL & Redis infrastructure
└── requirements.txt         # Dependencies
```

---

## 🚀 เริ่มต้นใช้งาน (Getting Started)

### 1. รัน Infrastructure ด้วย Docker
```bash
docker-compose up -d
```

### 2. ติดตั้ง Python Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 3. ตั้งค่าสภาพแวดล้อม
```bash
cp .env.example .env
# แก้ไข .env ใส่ค่า DATABASE_URL, REDIS_URL, SECRET_KEY, DEEPSEEK_API_KEY
```

### 4. รัน Database Migrations
```bash
alembic upgrade head
```

### 5. สตาร์ทระบบ
```bash
# Terminal 1: Web Server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Celery Worker
celery -A app.worker.celery_app.celery worker --loglevel=info -c 2
```

---

## 📄 เอกสารอ้างอิงเพิ่มเติม
- [CORE_WORKFLOW.md](CORE_WORKFLOW.md) — แผนผังกระบวนการทำงานทั้งระบบ
- [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) — สรุปการออกแบบสถาปัตยกรรมและ API Spec โดยละเอียด
- [ADMIN_PANEL.md](ADMIN_PANEL.md) — คู่มือการใช้งานระบบหลังบ้านสำหรับผู้ดูแล

---

<p align="center">
  พัฒนาโดย <a href="https://github.com/Punpun847">Punpun847</a>
</p>
