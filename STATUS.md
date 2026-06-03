# Status Snapshot — 2026-05-26 17:42

## 📊 Answer Bank Progress

| Course | Code | Title | Questions | Test Result |
|---|---|---|---|---|
| 1905 | WMD1044 | เรื่องเงินเด็กจบใหม่ต้องรู้ | 23 | ✅ 100% |
| 1906 | WMD1045 | เรื่องเงิน Sandwich Gen ต้องรู้ | 24 | ✅ 100% |
| 1907 | WMD1046 | เรื่องเงินวัยเกษียณต้องรู้ | 23 | ✅ 100% |
| 1937 | WMD1047 | เรื่องเงินมนุษย์เงินเดือนต้องรู้ | 23 | ⚠️ 80% (1 ข้อ Gemini ผิด) |
| 1938 | WMD1048 | เรื่องเงินฟรีแลนซ์ต้องรู้ | 24 | ✅ 100% |
| 1960 | WMD1701 | เงินทองต้องวางแผน ฉบับครอบครัว | 9 | ⚠️ exam pool ขาด (40%) |
| **รวม** | — | **6 courses** | **126 ข้อ** | **5/6 ✅** |

**Redis answer_bank:** 128 entries (126 จาก harvest + 2 sample)

## 📁 Files

```
questions/
  ├─ dump.json                      ← 126 ข้อมีเฉลย 100%
  ├─ answer_bank_2026-05-26.json    ← Redis backup
  └─ sample.json                    ← format example

prompts/
  ├─ prompt_1.txt → answers_1.txt  ← 30 ข้อแรก (apply แล้ว)
  ├─ prompt_2.txt → ...             ← 30 ข้อต่อมา
  ├─ prompt_3.txt → ...             ← 30 ข้อต่อมา
  ├─ prompt_4.txt → ...             ← 13 ข้อสุดท้าย
  └─ answers_all.txt                ← all 103 answers (applied)

backup-answer-bank-2026-05-26-1742.zip  ← Full backup (75 KB)
```

## 🔑 Credentials Used

- **SET-direct account** (kareemsaisaid@gmail.com / Kareem170117) ✅ Works
  - Access: SETGroup (~80 courses available)
  - Cannot access: SETStudentLoan (need DSL portal flow)
- **DSL portal** (3900300019919 / Kareem170117) ❌ 401-RMS-AU20202 (pwd wrong)

## 🎯 Coverage Analysis

| Scope | Total | Done | Coverage |
|---|---|---|---|
| SETGroup (kareem can access) | ~80 | 6 | 7.5% |
| WMD series ใน SETGroup | ~15 | 6 | 40% |
| SETStudentLoan (กยศ.) | ~72 | 0 | 0% (no DSL pwd) |

**Cross-pollination potential:**
- WMD content ใน SETStudentLoan = WMD content ใน SETGroup → cache hit ฟรี!
- ดังนั้น user กยศ. ที่เลือก WMD courses จะใช้ cache ที่เรา harvest แล้ว → ผ่านได้

## 🚀 To Resume

### รัน harvest course เพิ่ม:
```bash
cd "C:\Users\KK493\Downloads\gyso-backend-main (3)\gyso-backend-main"
$env:PYTHONPATH = ".\stubs;."

# popular courses ที่เหลือ
python scripts/dump_questions.py kareemsaisaid@gmail.com Kareem170117 \
    1823 1151 1854 --smart
```

### ทำเฉลย:
```bash
python scripts/make_prompt.py questions/dump.json --unanswered-only --chunk 30
# → ส่ง prompts/prompt_N.txt ไป Gemini
# → save JSON เป็น prompts/answers_N.txt
python scripts/apply_answers.py questions/dump.json prompts/answers_*.txt --import
```

### ทดสอบ:
```bash
python scripts/test_exam_with_cache.py kareemsaisaid@gmail.com Kareem170117 \
    1823 1151 1854
```

### List ทุก course ใน SETGroup:
```bash
python scripts/dump_questions.py kareemsaisaid@gmail.com Kareem170117 dummy --list-only
```

## 🔧 Known Issues

1. **1960 exam pool ขาด** — exam type ของ course 1960 ต่างจาก post-test
   - Fix: re-run `dump_questions.py ... 1960 --smart` (จะ pick up exam pool)
   - หรือ scrape exam page ตรงๆ (URL `/SETGroup/enroll/{eid}/exam/exam`)

2. **1937 พลาด 1 ข้อ** — Gemini ตอบผิด 1 ใน 5
   - ยังผ่าน 80% > 70% (cert ออก)
   - Fix: รัน `make_prompt.py --course 1937` + Gemini อีกครั้ง + apply --force

3. **DSL password 401** — บัญชี กยศ. login ไม่ได้
   - User ต้อง verify pwd manually หรือ reset

## 📈 Next Steps

1. **Backup ปัจจุบัน:** ✅ Done (zip 75 KB)
2. **เลือกทำต่อ:**
   - A: harvest 80 SETGroup ทั้งหมด (~5-6 ชม.)
   - B: pragmatic — เฉพาะ popular ~25 (~2 ชม.)
   - C: รอ DSL pwd → SETStudentLoan 72
3. **Deploy:** restart server + Celery worker → user ใช้ระบบได้
