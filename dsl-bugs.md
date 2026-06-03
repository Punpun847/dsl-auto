# DSL Bugs & Findings

อัปเดตล่าสุด: **2026-05-15 (session 2)**

---

## สิ่งที่ค้นพบจากการ debug

### ✅ Confirmed Facts

| # | สิ่งที่รู้ | หลักฐาน |
|---|-----------|---------|
| 1 | **course_id ใน URL คือตัวเลข** ไม่ใช่ code — เช่น `WMD1037s` → id `1942` | `_scrape_current_page:244` regex `/courses\/(\d+)/` |
| 2 | **URL จริงของหน้า course คือ `/courses/{id}/info`** (มี `/info`) ไม่ใช่ `/courses/{id}` | ทดสอบ goto ตรงๆ → 404, click จาก list → `/info` |
| 3 | **Session race:** หลัง click card จาก list → SPA render guest view ก่อน → ต้อง reload หน้า /info ถึง rehydrate เป็น logged-in view | เจอใน `inspect_course.py` หลายรอบ |
| 4 | **ปุ่ม "เข้าเรียน" และ "ลงทะเบียน" เป็น element เดียวกัน** class `.btn-trigger-enroll`, onclick = `enroll(cid, gkey, ...)` — text เปลี่ยนตาม enroll state | `debug_enter_btn.py` output |
| 5 | **click "เข้าเรียน/ลงทะเบียน" → เปิด `$.confirm` (jquery-confirm) popup** ถาม "คุณต้องการลงทะเบียน...?" มีปุ่ม ตกลง/ยกเลิก | `debug_enroll_api.py` output |
| 6 | **JS `enroll()` function flow:** GET `/api/site/groups/{gkey}/courses/{cid}` → ถ้า `enroll_chk=true` POST `/enroll2learning` → GET groups → `window.location.href = '/{gkey}/enroll/{eid}/{navigator}'` | source ของ `enroll()` function ใน browser |
| 7 | **POST `/api/site/enroll2learning` → 401** session ใช้ได้แค่ GET ไม่ valid สำหรับ POST — เมื่อ 401 JS ส่ง `postMessage("Login")` ไป parent → DSL portal kick user กลับ `wsa.dsl.studentloan.or.th/#/main` | `debug_enroll_api.py` response body |
| 8 | **`lessonsByCandidate` = `{}` ทุกครั้ง** — SET ปัจจุบันไม่ได้ใช้ class naming `.lesson-item/.episode-item/.chapter-item` | `inspect_course.py` JSON output |

---

## Bug List

| # | ปัญหา | ไฟล์ : Line | ระดับ | สถานะ |
|---|-------|-------------|------|-------|
| 1 | **POST `/enroll2learning` → 401** — session ไม่ valid สำหรับ POST (อาจขาด CSRF token หรือ Authorization header) กระทบทั้ง watch flow | cross-cutting | 🔴 Critical | ✅ แก้แล้ว |
| 2 | `_enter_course` ไม่ handle `$.confirm` modal — click ปุ่มแล้ว return เลย ไม่กด "ตกลง" | `dsl_client.py:415-433` | 🔴 | ✅ แก้แล้ว |
| 3 | `_enter_course` ใช้ `wait_for_load_state("networkidle")` — SET มี GA/FB pixel/sharethis ส่ง request ตลอด → never idle → timeout 15 วิ → `except: continue` กลืน error | `dsl_client.py:429` | 🔴 | ✅ แก้แล้ว (ทั้งไฟล์) |
| 4 | `_enter_course` ไม่ handle 401 / page navigate ออกจาก SET — ถ้า POST พัง page ไป DSL แล้ว _collect_lessons ทุกอย่างพัง | `dsl_client.py:415-433` | 🔴 | ✅ แก้แล้ว |
| 5 | `_collect_lessons` selectors ไม่ตรง SET จริง → fall through → assume single-video → คอร์สหลาย lesson ทำงานไม่ได้ | `dsl_client.py:438-470` | 🟡 | ❌ ยังไม่แก้ (รอเข้า player จริงก่อน) |
| 6 | `SET_COURSE_URL` ขาด `/info` → goto ตรงๆ ได้หน้า 404 | `dsl_client.py:20` | 🟡 | ✅ แก้แล้ว |
| 7 | `inspect_list.py` (script เก่า) ไปหน้า list โดยไม่ login ก่อน — ใช้งานไม่ได้ | `scripts/inspect_list.py` | 🟢 cleanup | ❌ |

---

## ยังไม่ verify (อาจมีปัญหาเพิ่ม)

ติด 401 ก่อน เลยยังเข้า player จริงไม่ได้ — functions เหล่านี้ยังไม่ได้ตรวจ:

- `_play_until_end` (line 493) / `_play_in_frame` (line 543)
- `_do_quiz` (line 563) — quiz selectors ยังไม่ verify
- `_download_cert` (line 605) — PDF download flow ยังไม่ verify
- **Pretest ก่อนเรียน** — user แจ้งว่ามีแบบทดสอบก่อนเรียน (pretest) ก่อนถึง player — ยังไม่มี logic handle ใน production code

---

## Next Steps (เรียงลำดับ)

1. ~~แก้ bug #1 (401)~~ ✅ เสร็จแล้ว — root cause: `expect_page` ใน `goto_set` ไม่ yield event loop หลัง click → Angular เปิด SET tab แต่ Playwright จับไม่ทัน → ใช้ guest session → 401. Fix: เพิ่ม `asyncio.sleep(5)` ใน `async with ctx.expect_page()` block

2. ~~แก้ bug #2 + #3 + #4 + #6~~ ✅ เสร็จแล้ว (session 2)

3. **🔴 แก้ bug #5 `_collect_lessons` + `_play_until_end`**
   - ต้อง inspect หน้า player จริงๆ ก่อน (หลังเข้าได้) แล้ว map selector ที่ตรง

4. **🟡 verify** `_play_until_end`, `_do_quiz`, `_download_cert` + handle pretest

---

## ค่าอ้างอิงสำหรับ test

(จาก `find_enrolled.py` run วันที่ 2026-05-15)

| course_id | code | สถานะ | title |
|-----------|------|-------|-------|
| 1941 | WMD1036s | enrolled | สร้าง Growth Mindset เทรนด์ใหม่ของคนวัยทำงาน |
| 1298 | ACC1001s | enrolled | The Role of Accounting for Business |
| 1296 | MKD1004 | enrolled | Customer Validation |
| 1295 | MKD1002s | enrolled | UX Development |
| 1942 | WMD1037s | ยังไม่ enrolled | เตรียมความพร้อมด้านภาษา ก้าวสู่ Global Citizen |

user มี ~72 courses ใน list ทั้งหมด
