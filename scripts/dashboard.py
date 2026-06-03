"""Simple HTTP dashboard — เปิดที่ http://localhost:9000

แสดงสถานะทุก job ในรอบ 2 ชม.ล่าสุด พร้อม progress bar
Refresh ทุก 5 วินาที
"""
import hashlib
import http.server
import json
import os
import socketserver
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs

import redis as _redis
from sqlalchemy import create_engine, text

ROOT = Path(__file__).parent.parent

# โหลด .env (ถ้ามี python-dotenv) — dashboard รัน standalone ไม่ผ่าน FastAPI
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# DB URL: รับจาก env เท่านั้น — ไม่ hardcode credentials
# pydantic-settings ใช้ +asyncpg ใน FastAPI แต่ sqlalchemy sync ต้องตัดออก
_db_url = os.getenv("DATABASE_URL", "")
if _db_url.startswith("postgresql+asyncpg://"):
    _db_url = _db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
DB = _db_url or "postgresql://gyso@localhost:5432/gyso_db"  # fallback ไม่มี password
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PORT = int(os.getenv("DASHBOARD_PORT", "9000"))


def fetch_pending_exams():
    """ดึงคำถามที่รอ human ตอบจาก Redis"""
    try:
        r = _redis.from_url(REDIS_URL, decode_responses=True)
        keys = r.keys("exam:human:*")
        # กรองเฉพาะ keys คำถาม (ไม่ใช่ answer keys)
        pending = []
        for key in keys:
            if ":answer:" not in key:
                raw = r.get(key)
                if raw:
                    try:
                        data = json.loads(raw)
                        # กรอง expired
                        if data.get("expires_at", 0) > time.time():
                            pending.append(data)
                    except Exception:
                        pass
        r.close()
        return pending
    except Exception:
        return []

def _load_nid_map() -> dict:
    """build {sha256(nid): nid} จาก accounts.csv (batch ปัจจุบัน) + nid_registry.json (สะสมถาวร).
    เรียกซ้ำได้ — fetch_data() เรียกทุกรอบ refresh ให้เห็น job ใหม่โดยไม่ต้อง restart dashboard."""
    m: dict = {}
    # 1. accounts.csv — batch ปัจจุบัน
    try:
        with open(ROOT / "accounts.csv", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if "," in line:
                    nid = line.split(",")[0].strip()
                    if nid:
                        m[hashlib.sha256(nid.encode()).hexdigest()] = nid
    except FileNotFoundError:
        pass
    # 2. nid_registry.json — สะสมทุก job ที่เคย submit (ครอบคลุม job เก่าที่ NID หลุด accounts.csv)
    try:
        reg = ROOT / "nid_registry.json"
        if reg.exists():
            m.update(json.loads(reg.read_text(encoding="utf-8")))
    except Exception:
        pass
    return m


NID_MAP = _load_nid_map()

# โหลด mapping NID → ชื่อจริง จากไฟล์ private_names.json (gitignored)
# ถ้าไฟล์ไม่มี dashboard จะแสดง "?" แทนชื่อ — ไม่ break
NAMES: dict[str, str] = {}
_names_path = ROOT / "private_names.json"
if _names_path.exists():
    try:
        with open(_names_path, encoding="utf-8") as _f:
            NAMES = {k: v for k, v in json.load(_f).items() if not k.startswith("_")}
    except Exception as _e:
        print(f"⚠️  อ่าน private_names.json ไม่ได้: {_e}", file=sys.stderr)


def _fmt_duration(seconds: float) -> str:
    """แปลงวินาทีเป็น '1h 23m' หรือ '12m 34s' หรือ '45s'"""
    s = int(max(0, seconds))
    if s >= 3600:
        return f"{s//3600}h {(s%3600)//60}m"
    if s >= 60:
        return f"{s//60}m {s%60}s"
    return f"{s}s"


def fetch_data():
    global NID_MAP
    NID_MAP = _load_nid_map()  # refresh ทุกรอบ — เห็น NID จาก job ที่เพิ่ง submit (registry อัปเดตสด)
    engine = create_engine(DB)
    hours = int(os.getenv("DASHBOARD_WINDOW_HOURS", "6"))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    now_utc = datetime.now(timezone.utc)
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT id, status, nid_hash, courses, total_hours, created_at, completed_at "
            "FROM jobs WHERE created_at > :cutoff ORDER BY created_at DESC"
        ), {"cutoff": cutoff}).fetchall()
        result = []
        for r in rows:
            jid, status, nid_hash, courses, total_hours, created, completed = r
            nid = NID_MAP.get(nid_hash, "?")
            name = NAMES.get(nid, "")
            n_total = len(courses) if courses else 0

            # Certs ของ job นี้ — ดึงทั้งหมด แล้ว map กับ course_id
            certs = c.execute(text(
                "SELECT course_id, pdf_path, issued_at FROM certificates "
                "WHERE job_id = :j ORDER BY issued_at"
            ), {"j": str(jid)}).fetchall()
            cert_map = {row[0]: {"pdf": row[1], "at": row[2]} for row in certs}
            n_done = sum(1 for v in cert_map.values() if v["pdf"])
            n_attempted = len(cert_map)

            # Latest log — sys/ok/err message ล่าสุด
            log_row = c.execute(text(
                "SELECT type, message, progress, created_at FROM job_logs "
                "WHERE job_id = :j ORDER BY created_at DESC LIMIT 1"
            ), {"j": str(jid)}).fetchone()
            latest_log = None
            if log_row:
                latest_log = {
                    "type": log_row[0],
                    "msg": log_row[1],
                    "progress": log_row[2],
                    "ago": _fmt_duration((now_utc - log_row[3]).total_seconds()),
                }

            # Current course — course แรกใน list ที่ยังไม่ได้ cert (เดาว่า worker ทำอยู่)
            current_course = None
            if status == "running" and courses:
                for cid in courses:
                    if cid not in cert_map:
                        current_course = str(cid)
                        break

            # Elapsed + ETA
            elapsed_sec = (now_utc - created).total_seconds() if status == "running" else None
            eta = None
            if status == "running" and n_attempted > 0 and n_total > n_attempted:
                avg_per_cert = elapsed_sec / n_attempted
                eta = avg_per_cert * (n_total - n_attempted)

            # Build per-course list (สำหรับ expandable row)
            course_details = []
            for cid in (courses or []):
                cinfo = cert_map.get(cid)
                if cinfo and cinfo["pdf"]:
                    course_details.append({"id": str(cid), "state": "done", "pdf": cinfo["pdf"]})
                elif cinfo:
                    course_details.append({"id": str(cid), "state": "attempted", "pdf": None})
                elif str(cid) == current_course:
                    course_details.append({"id": str(cid), "state": "running", "pdf": None})
                else:
                    course_details.append({"id": str(cid), "state": "pending", "pdf": None})

            result.append({
                "job_id": str(jid)[:8],
                "job_id_full": str(jid),
                "status": status,
                "nid": nid,
                "name": name,
                "total": n_total,
                "attempted": n_attempted,
                "done": n_done,
                "target_hours": total_hours,
                "created": created.strftime("%H:%M:%S"),
                "completed": completed.strftime("%H:%M:%S") if completed else None,
                "elapsed": _fmt_duration(elapsed_sec) if elapsed_sec else None,
                "eta": _fmt_duration(eta) if eta else None,
                "current_course": current_course,
                "latest_log": latest_log,
                "courses": course_details,
            })
        return result


# Cache LLM stats — log parsing แพง, refresh ทุก 10 วินาที
_llm_stats_cache = {"data": None, "ts": 0.0}
_LLM_STATS_TTL = 10.0


def fetch_llm_stats():
    """ดึงสถิติ LLM/cache — cache size (live จาก Redis) + LLM calls วันนี้ (cached 10s)"""
    now = time.time()
    if _llm_stats_cache["data"] and (now - _llm_stats_cache["ts"]) < _LLM_STATS_TTL:
        cached = dict(_llm_stats_cache["data"])
        # cache size live (เร็ว — HLEN เป็น O(1))
        try:
            r = _redis.from_url(REDIS_URL, decode_responses=True)
            cached["cache_size"] = r.hlen("dsl:answer_cache")
            r.close()
        except Exception:
            pass
        return cached

    stats = {"cache_size": 0, "deepseek_calls": 0, "claude_calls": 0, "human_calls": 0}
    try:
        r = _redis.from_url(REDIS_URL, decode_responses=True)
        stats["cache_size"] = r.hlen("dsl:answer_cache")
        r.close()
    except Exception:
        pass

    # Parse celery log วันนี้ — นับจำนวน LLM calls
    today = datetime.now().strftime("%Y-%m-%d")
    for i in range(1, 5):
        log_path = ROOT / f"celery{i}.log"
        if not log_path.exists():
            continue
        try:
            with open(log_path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if today not in line:
                        continue
                    if "LLM: DeepSeek" in line:
                        stats["deepseek_calls"] += 1
                    elif "LLM: Claude" in line:
                        stats["claude_calls"] += 1
                    elif "🙋 รอ human" in line:
                        stats["human_calls"] += 1
        except Exception:
            continue

    _llm_stats_cache["data"] = stats
    _llm_stats_cache["ts"] = now
    return stats


def render_pending_exams(pending):
    if not pending:
        return ""
    cards = []
    for p in pending:
        job_id = p.get("job_id", "?")
        course_id = p.get("course_id", "?")
        exam_type = p.get("exam_type", "exam")
        attempt = p.get("attempt", 0)
        questions = p.get("questions", [])
        expires_at = p.get("expires_at", 0)
        secs_left = max(0, int(expires_at - time.time()))
        mins = secs_left // 60
        secs = secs_left % 60

        q_html = ""
        for q in questions:
            idx = q["idx"]
            need = q["need_answer"]
            label_color = "#f38ba8" if need else "#a6e3a1"
            badge = "❓ ต้องตอบ" if need else "✅ มีใน cache"
            opts_html = "".join(
                f'<label style="display:block;margin:4px 0;cursor:pointer;">'
                f'<input type="radio" name="q{idx}" value="{oi}" required> {opt}</label>'
                for oi, opt in enumerate(q["options"])
            )
            q_html += f"""
<div style="background:#1e1e2e;padding:12px;border-radius:6px;margin:8px 0;border-left:3px solid {label_color};">
  <div style="font-size:12px;color:{label_color};margin-bottom:6px;">{badge} &nbsp; ข้อ {idx+1}</div>
  <div style="margin-bottom:8px;line-height:1.5;">{q["q_text"]}</div>
  {opts_html}
</div>"""

        cards.append(f"""
<div style="background:#181825;border:2px solid #f38ba8;border-radius:10px;padding:20px;margin-bottom:20px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <div>
      <span style="color:#f38ba8;font-weight:700;font-size:16px;">🙋 รอคำตอบ!</span>
      <span style="margin-left:12px;color:#cba6f7;">Job: {job_id}</span>
      <span style="margin-left:8px;color:#94e2d5;">Course: {course_id}</span>
      <span style="margin-left:8px;color:#f9e2af;">{exam_type} attempt {attempt}</span>
    </div>
    <div style="color:#f9e2af;font-size:13px;">⏱ เหลือ {mins}:{secs:02d}</div>
  </div>
  <form method="POST" action="/answer">
    <input type="hidden" name="job_id" value="{p.get('job_id','')}">
    <input type="hidden" name="course_id" value="{course_id}">
    <input type="hidden" name="n_questions" value="{len(questions)}">
    {q_html}
    <button type="submit" style="margin-top:16px;background:#a6e3a1;color:#1e1e2e;border:none;padding:10px 28px;border-radius:8px;font-size:15px;font-weight:700;cursor:pointer;">
      ✅ ส่งคำตอบ
    </button>
  </form>
</div>""")

    return f"""
<div id="pending-exams" style="margin-bottom:20px;">
  <h2 style="color:#f38ba8;margin:0 0 12px;">🚨 รอคำตอบจากคุณ ({len(pending)} รายการ)</h2>
  {"".join(cards)}
</div>"""


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<title>GYSO Dashboard</title>
<style>
  body {{ font-family: 'Segoe UI', -apple-system, sans-serif; background: #1e1e2e; color: #cdd6f4; padding: 20px; margin: 0; }}
  h1 {{ color: #89b4fa; margin: 0 0 10px; }}
  .meta {{ color: #6c7086; font-size: 13px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; background: #181825; border-radius: 8px; overflow: hidden; }}
  th {{ background: #313244; padding: 10px; text-align: left; font-size: 12px; color: #cba6f7; }}
  td {{ padding: 10px; border-top: 1px solid #313244; font-size: 13px; vertical-align: middle; }}
  tr.job-row {{ cursor: pointer; }}
  tr.job-row:hover {{ background: #313244; }}
  tr.detail-row {{ display: none; }}
  tr.detail-row.open {{ display: table-row; }}
  tr.detail-row td {{ background: #11111b; padding: 16px 24px; }}
  .status {{ padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; white-space: nowrap; }}
  .status-done {{ background: #a6e3a1; color: #1e1e2e; }}
  .status-running {{ background: #f9e2af; color: #1e1e2e; animation: pulse 1.5s infinite; }}
  .status-failed {{ background: #f38ba8; color: #1e1e2e; }}
  .status-queued {{ background: #74c7ec; color: #1e1e2e; }}
  .status-pending {{ background: #6c7086; color: #cdd6f4; }}
  @keyframes pulse {{ 50% {{ opacity: 0.6; }} }}
  .progress-bar {{ width: 160px; height: 18px; background: #313244; border-radius: 9px; overflow: hidden; position: relative; }}
  .progress-fill {{ height: 100%; background: linear-gradient(90deg, #89b4fa, #cba6f7); transition: width 0.5s; }}
  .progress-text {{ position: absolute; top: 0; left: 0; right: 0; bottom: 0; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; color: #1e1e2e; }}
  .summary {{ display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }}
  .summary-card {{ background: #181825; padding: 12px 16px; border-radius: 8px; flex: 1; min-width: 130px; }}
  .summary-card .num {{ font-size: 24px; font-weight: 700; color: #89b4fa; }}
  .summary-card .label {{ font-size: 11px; color: #6c7086; text-transform: uppercase; }}
  .nid {{ font-family: monospace; color: #94e2d5; font-size: 12px; }}
  .name {{ font-weight: 500; }}
  .log-line {{ color: #a6adc8; font-size: 11px; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .log-sys {{ color: #89b4fa; }}
  .log-ok {{ color: #a6e3a1; }}
  .log-err {{ color: #f38ba8; }}
  .log-done {{ color: #cba6f7; }}
  .log-play {{ color: #94e2d5; }}
  .time-meta {{ color: #6c7086; font-size: 11px; }}
  .toggle-icon {{ color: #6c7086; transition: transform 0.2s; display: inline-block; width: 14px; }}
  tr.job-row.open .toggle-icon {{ transform: rotate(90deg); color: #cba6f7; }}
  .filter-bar {{ display: flex; gap: 8px; margin: 12px 0; flex-wrap: wrap; }}
  .filter-bar input, .filter-bar select {{ background: #181825; color: #cdd6f4; border: 1px solid #313244; border-radius: 6px; padding: 6px 10px; font-size: 13px; }}
  .filter-bar input:focus, .filter-bar select:focus {{ border-color: #89b4fa; outline: none; }}
  .course-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; margin-top: 8px; }}
  .course-item {{ background: #1e1e2e; padding: 8px 12px; border-radius: 6px; border-left: 3px solid; display: flex; justify-content: space-between; align-items: center; }}
  .course-item.done {{ border-left-color: #a6e3a1; }}
  .course-item.attempted {{ border-left-color: #f9e2af; }}
  .course-item.running {{ border-left-color: #89b4fa; }}
  .course-item.pending {{ border-left-color: #6c7086; }}
  .course-id {{ font-family: monospace; font-size: 12px; }}
  .course-item .pdf-link {{ color: #94e2d5; font-size: 11px; text-decoration: none; }}
  .detail-meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; padding-bottom: 10px; }}
  .meta-cell {{ font-size: 12px; }}
  .meta-cell .l {{ color: #6c7086; text-transform: uppercase; font-size: 10px; }}
  .meta-cell .v {{ color: #cdd6f4; font-weight: 500; margin-top: 2px; }}
</style>
<script>
  var refreshSecs = {refresh};
  var timer = null;
  var paused = false;

  function startTimer() {{
    if (timer) clearTimeout(timer);
    timer = setTimeout(function() {{
      if (!paused) location.reload();
      else startTimer();
    }}, refreshSecs * 1000);
  }}

  function toggleRow(jobId) {{
    var row = document.querySelector('tr.job-row[data-job="' + jobId + '"]');
    var detail = document.querySelector('tr.detail-row[data-job="' + jobId + '"]');
    if (row && detail) {{
      row.classList.toggle("open");
      detail.classList.toggle("open");
    }}
  }}

  function applyFilters() {{
    var q = document.getElementById("flt-search").value.toLowerCase();
    var s = document.getElementById("flt-status").value;
    document.querySelectorAll("tr.job-row").forEach(function(row) {{
      var nid = row.dataset.nid || "";
      var name = row.dataset.name || "";
      var status = row.dataset.status || "";
      var matchQ = !q || nid.toLowerCase().includes(q) || name.toLowerCase().includes(q);
      var matchS = !s || status === s;
      var show = matchQ && matchS;
      row.style.display = show ? "" : "none";
      var detail = document.querySelector('tr.detail-row[data-job="' + row.dataset.job + '"]');
      if (detail && !show) detail.classList.remove("open");
      if (detail && !show) detail.style.display = "none";
      else if (detail) detail.style.display = "";
    }});
  }}

  document.addEventListener("DOMContentLoaded", function() {{
    // หยุด refresh ทันทีที่ user แตะ form/filter
    document.querySelectorAll("input[type=radio], button[type=submit], #flt-search, #flt-status, input[type=password]").forEach(function(el) {{
      el.addEventListener("focus", function() {{
        paused = true;
        if (timer) clearTimeout(timer);
        document.getElementById("refresh-status").textContent = "⏸ หยุด refresh — กำลังใช้งาน";
      }});
    }});
    document.querySelectorAll("tr.job-row").forEach(function(row) {{
      row.addEventListener("click", function(e) {{
        if (e.target.tagName === "A") return;
        toggleRow(row.dataset.job);
      }});
    }});
    var s1 = document.getElementById("flt-search");
    var s2 = document.getElementById("flt-status");
    if (s1) s1.addEventListener("input", applyFilters);
    if (s2) s2.addEventListener("change", applyFilters);
    startTimer();
  }});
</script>
</head>
<body>
<h1>🎓 GYSO Automation Dashboard</h1>
<div class="meta">อัปเดตล่าสุด: {now} &nbsp;|&nbsp; <span id="refresh-status">🔄 refresh ทุก {refresh} วินาที</span> &nbsp;|&nbsp; คลิกแถวเพื่อดูรายละเอียด course</div>

{pending_html}
<div class="summary">
  <div class="summary-card"><div class="num">{n_total}</div><div class="label">Jobs ({window}h)</div></div>
  <div class="summary-card"><div class="num" style="color:#a6e3a1;">{n_done}</div><div class="label">Done</div></div>
  <div class="summary-card"><div class="num" style="color:#f9e2af;">{n_run}</div><div class="label">Running</div></div>
  <div class="summary-card"><div class="num" style="color:#f38ba8;">{n_failed}</div><div class="label">Failed</div></div>
  <div class="summary-card"><div class="num" style="color:#a6e3a1;">{certs_total}</div><div class="label">Certs Issued</div></div>
  <div class="summary-card"><div class="num" style="color:#cba6f7;">{cache_size}</div><div class="label">Cache Entries</div></div>
  <div class="summary-card"><div class="num" style="color:#94e2d5;">{deepseek_calls}</div><div class="label">DeepSeek Calls</div></div>
  <div class="summary-card"><div class="num" style="color:#f9e2af;">{claude_calls}</div><div class="label">Claude Calls</div></div>
  <div class="summary-card"><div class="num" style="color:#f38ba8;">{human_calls}</div><div class="label">Asked Human</div></div>
</div>

<div class="filter-bar">
  <input id="flt-search" type="text" placeholder="🔍 ค้นหา ชื่อ / NID …" style="flex:1;min-width:220px;">
  <select id="flt-status">
    <option value="">— ทุก status —</option>
    <option value="running">Running</option>
    <option value="done">Done</option>
    <option value="failed">Failed</option>
    <option value="queued">Queued</option>
    <option value="pending">Pending</option>
  </select>
</div>

<table>
<thead><tr>
  <th style="width:30px;"></th>
  <th>Job</th><th>ชื่อ</th><th>NID</th><th>Status</th><th>📑 PDF</th><th>Progress</th>
  <th>Hours</th><th>Elapsed / ETA</th><th>Latest log</th><th>Created</th>
</tr></thead>
<tbody>
{rows}
</tbody>
</table>
</body></html>"""


def _render_merge_cell(d):
    """ปุ่ม PDF เล็กๆ ใน main row — เห็นชัดไม่ต้องคลิกขยาย
       - มี merged + done → 📑 ดาวน์โหลด (เขียว)
       - done แต่ยังไม่ merge → 🔄 รวม PDF (ฟ้า)
       - running/queued/failed → "—"
    """
    nid = d.get("nid", "")
    status = d.get("status", "")
    if not nid or nid == "?":
        return '<span style="color:#6c7086;">—</span>'

    merged = _find_merged_pdf(nid)
    if merged:
        size_kb = merged.stat().st_size // 1024
        return (
            f'<a href="/merged?nid={nid}" target="_blank" title="ขนาด {size_kb} KB" '
            f'style="background:#a6e3a1;color:#1e1e2e;padding:4px 10px;border-radius:5px;'
            f'font-weight:600;text-decoration:none;font-size:11px;white-space:nowrap;">'
            f'📑 ดาวน์โหลด</a>'
        )
    if status == "done":
        return (
            f'<form method="POST" action="/merge" style="display:inline;margin:0;">'
            f'<input type="hidden" name="nid" value="{nid}">'
            f'<input type="hidden" name="days" value="7">'
            f'<button type="submit" title="รวม cert PDF ทั้งหมดในรอบ 7 วัน" '
            f'style="background:#89b4fa;color:#1e1e2e;border:none;padding:4px 10px;'
            f'border-radius:5px;font-weight:600;cursor:pointer;font-size:11px;white-space:nowrap;">'
            f'🔄 รวม PDF</button></form>'
        )
    return '<span style="color:#6c7086;">—</span>'


def _find_merged_pdf(nid: str):
    """หาไฟล์ merged PDF ของ NID นี้ — รองรับชื่อแบบ '<NID>.pdf' และ '<NID> ...pdf'
    คืน (Path, mtime) ของไฟล์ล่าสุด หรือ None"""
    if not nid or not nid.isdigit():
        return None
    out_dir = ROOT / "certs"
    if not out_dir.exists():
        return None
    matches = list(out_dir.glob(f"{nid}*.pdf"))
    if not matches:
        return None
    latest = max(matches, key=lambda p: p.stat().st_mtime)
    return latest


def _render_course_detail(d):
    """Build expandable per-course breakdown + metadata"""
    courses = d.get("courses") or []
    if not courses and not d.get("latest_log"):
        return "<em style='color:#6c7086;'>ไม่มีรายละเอียด</em>"

    # Meta block
    log = d.get("latest_log") or {}
    log_msg = log.get("msg", "-")
    log_type = log.get("type", "")
    log_ago = log.get("ago", "")

    # Merged PDF — หาไฟล์ใน certs/<NID>*.pdf
    nid = d.get("nid", "")
    merged = _find_merged_pdf(nid) if nid and nid != "?" else None
    if merged:
        size_kb = merged.stat().st_size // 1024
        mtime = datetime.fromtimestamp(merged.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        merged_html = (
            f'<a href="/merged?nid={nid}" target="_blank" '
            f'style="background:#a6e3a1;color:#1e1e2e;padding:6px 14px;border-radius:6px;'
            f'font-weight:600;text-decoration:none;font-size:12px;display:inline-block;">'
            f'📑 ดาวน์โหลด Merged PDF ({size_kb} KB · {mtime})</a>'
            f' <form method="POST" action="/merge" style="display:inline;margin-left:6px;">'
            f'<input type="hidden" name="nid" value="{nid}">'
            f'<input type="hidden" name="days" value="7">'
            f'<button type="submit" style="background:#f9e2af;color:#1e1e2e;border:none;'
            f'padding:6px 12px;border-radius:6px;font-weight:600;cursor:pointer;font-size:12px;">'
            f'🔄 รวมใหม่ (7 วัน)</button></form>'
        )
    elif nid and nid != "?":
        merged_html = (
            f'<span style="color:#6c7086;font-size:12px;">ยังไม่ได้รวม PDF</span>'
            f' <form method="POST" action="/merge" style="display:inline;margin-left:6px;">'
            f'<input type="hidden" name="nid" value="{nid}">'
            f'<input type="hidden" name="days" value="7">'
            f'<button type="submit" style="background:#a6e3a1;color:#1e1e2e;border:none;'
            f'padding:6px 14px;border-radius:6px;font-weight:600;cursor:pointer;font-size:12px;">'
            f'📑 รวม PDF ตอนนี้ (7 วัน)</button></form>'
        )
    else:
        merged_html = '<span style="color:#6c7086;font-size:12px;">ไม่ทราบ NID</span>'

    # ปุ่มซ่อม — แสดงเฉพาะ attempted courses (cert record มีแต่ pdf_path=NULL)
    attempted_courses = [c["id"] for c in courses if c["state"] == "attempted"]
    if attempted_courses and nid and nid != "?":
        course_list = ", ".join(attempted_courses)
        courses_val = ",".join(attempted_courses)
        repair_html = f"""
<div style="margin:10px 0 12px;padding:12px 16px;background:#1e1e2e;border-radius:8px;border:1px solid #f9e2af;">
  <div style="color:#f9e2af;font-weight:600;margin-bottom:10px;">
    ⚠️ {len(attempted_courses)} คอร์สขาด PDF &nbsp;—&nbsp; <code style="font-size:12px;">{course_list}</code>
  </div>
  <form method="POST" action="/repair" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
    <input type="hidden" name="job_id" value="{d['job_id_full']}">
    <input type="hidden" name="nid" value="{nid}">
    <input type="hidden" name="courses" value="{courses_val}">
    <input type="password" name="pwd" placeholder="🔑 รหัสผ่าน กยศ." required autocomplete="current-password"
           style="background:#313244;color:#cdd6f4;border:1px solid #6c7086;border-radius:6px;
                  padding:6px 10px;font-size:13px;width:200px;">
    <button type="submit"
            style="background:#f9e2af;color:#1e1e2e;border:none;padding:7px 16px;
                   border-radius:6px;font-weight:700;cursor:pointer;font-size:13px;">
      🔧 ซ่อม {len(attempted_courses)} คอร์ส
    </button>
  </form>
</div>"""
    else:
        repair_html = ""

    meta_html = f"""
<div class="detail-meta">
  <div class="meta-cell"><div class="l">Job ID</div><div class="v"><code>{d['job_id_full']}</code></div></div>
  <div class="meta-cell"><div class="l">Target Hours</div><div class="v">{d.get('target_hours','-')}</div></div>
  <div class="meta-cell"><div class="l">Current Course</div><div class="v">{d.get('current_course') or '-'}</div></div>
  <div class="meta-cell"><div class="l">Elapsed</div><div class="v">{d.get('elapsed') or '-'}</div></div>
  <div class="meta-cell"><div class="l">ETA (เหลือ)</div><div class="v">{d.get('eta') or '-'}</div></div>
  <div class="meta-cell"><div class="l">Latest Log ({log_ago} ago)</div><div class="v log-{log_type}">{log_msg}</div></div>
</div>
<div style="padding:8px 0 12px;border-bottom:1px solid #313244;margin-bottom:12px;">{merged_html}</div>
{repair_html}"""

    # Course grid
    items = []
    badge = {"done": "✅", "attempted": "⚠️", "running": "▶️", "pending": "⏳"}
    job_id_full = d["job_id_full"]
    for c in courses:
        st = c["state"]
        pdf = c.get("pdf")
        # serve PDF ผ่าน /cert route — browser block file:// link ที่ originate จาก http://
        pdf_link = (
            f'<a class="pdf-link" href="/cert?job={job_id_full}&course={c["id"]}" target="_blank">PDF ↗</a>'
            if pdf else ""
        )
        items.append(
            f'<div class="course-item {st}">'
            f'<span class="course-id">{badge.get(st,"")} {c["id"]}</span>'
            f'{pdf_link}'
            f'</div>'
        )
    grid_html = f'<div class="course-grid">{"".join(items)}</div>' if items else ""

    return meta_html + grid_html


def render(data, pending, llm_stats):
    n_total = len(data)
    n_done = sum(1 for d in data if d["status"] == "done")
    n_run = sum(1 for d in data if d["status"] == "running")
    n_failed = sum(1 for d in data if d["status"] == "failed")
    certs_total = sum(d["done"] for d in data)

    rows = []
    for d in data:
        pct = (d["done"] / d["total"] * 100) if d["total"] else 0
        log = d.get("latest_log") or {}
        log_msg = log.get("msg", "-")
        log_type = log.get("type", "")
        log_ago = log.get("ago", "")
        log_cell = f'<div class="log-line log-{log_type}" title="{log_msg}">{log_msg}</div>' \
                   f'<div class="time-meta">{log_ago} ago</div>' if log else '<span class="time-meta">-</span>'

        elapsed_eta = ""
        if d.get("elapsed"):
            elapsed_eta = f'<div>{d["elapsed"]}</div>'
            if d.get("eta"):
                elapsed_eta += f'<div class="time-meta">เหลือ ~{d["eta"]}</div>'
        elif d.get("completed"):
            elapsed_eta = f'<div class="time-meta">done {d["completed"]}</div>'
        else:
            elapsed_eta = '<span class="time-meta">-</span>'

        nid_display = d["nid"]
        rows.append(f"""
<tr class="job-row" data-job="{d['job_id']}" data-nid="{d['nid']}" data-name="{d['name']}" data-status="{d['status']}">
  <td><span class="toggle-icon">▶</span></td>
  <td><code>{d['job_id']}</code></td>
  <td class="name">{d['name']}</td>
  <td class="nid">{nid_display}</td>
  <td><span class="status status-{d['status']}">{d['status']}</span></td>
  <td>{_render_merge_cell(d)}</td>
  <td>
    <div class="progress-bar">
      <div class="progress-fill" style="width:{pct:.0f}%"></div>
      <div class="progress-text">{d['done']}/{d['total']}</div>
    </div>
  </td>
  <td>{d.get('target_hours','-')}</td>
  <td>{elapsed_eta}</td>
  <td>{log_cell}</td>
  <td class="time-meta">{d['created']}</td>
</tr>
<tr class="detail-row" data-job="{d['job_id']}">
  <td colspan="11">{_render_course_detail(d)}</td>
</tr>""")

    pending_html = render_pending_exams(pending)
    refresh = 3 if pending else 5

    window_h = int(os.getenv("DASHBOARD_WINDOW_HOURS", "6"))
    return HTML_TEMPLATE.format(
        now=datetime.now().strftime("%H:%M:%S"),
        n_total=n_total, n_done=n_done, n_run=n_run, n_failed=n_failed,
        certs_total=certs_total, rows="".join(rows),
        pending_html=pending_html, refresh=refresh,
        cache_size=llm_stats.get("cache_size", 0),
        deepseek_calls=llm_stats.get("deepseek_calls", 0),
        claude_calls=llm_stats.get("claude_calls", 0),
        human_calls=llm_stats.get("human_calls", 0),
        window=window_h,
    )


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            try:
                data = fetch_data()
                pending = fetch_pending_exams()
                llm_stats = fetch_llm_stats()
                html = render(data, pending, llm_stats)
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error: {e}".encode())
        elif self.path.startswith("/cert"):
            self._serve_cert()
        elif self.path.startswith("/merged"):
            self._serve_merged()
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_merged(self):
        """Serve merged PDF: /merged?nid=<NID> — หาไฟล์ใน certs/<NID>*.pdf ล่าสุด"""
        from urllib.parse import urlparse, parse_qs as _pq
        try:
            qs = _pq(urlparse(self.path).query)
            nid = (qs.get("nid", [""])[0] or "").strip()
            if not nid.isdigit():
                self.send_response(400); self.end_headers()
                self.wfile.write(b"invalid nid")
                return

            merged = _find_merged_pdf(nid)
            if not merged or not merged.exists():
                self.send_response(404); self.end_headers()
                self.wfile.write(b"merged pdf not found")
                return

            with open(merged, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition",
                             f'inline; filename="{nid}_merged.pdf"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500); self.end_headers()
            self.wfile.write(f"Error: {e}".encode())

    def _serve_cert(self):
        """Serve PDF cert: /cert?job=<uuid>&course=<id>
        Path traversal-safe: ใช้ DB lookup, ไม่รับ path จาก client"""
        from urllib.parse import urlparse, parse_qs as _pq
        try:
            qs = _pq(urlparse(self.path).query)
            job_id = (qs.get("job", [""])[0] or "").strip()
            course_id = (qs.get("course", [""])[0] or "").strip()
            if not job_id or not course_id:
                self.send_response(400); self.end_headers()
                self.wfile.write(b"missing job or course param")
                return

            engine = create_engine(DB)
            with engine.connect() as c:
                row = c.execute(text(
                    "SELECT pdf_path FROM certificates "
                    "WHERE job_id = :j AND course_id = :c AND pdf_path IS NOT NULL "
                    "LIMIT 1"
                ), {"j": job_id, "c": course_id}).fetchone()

            if not row or not row[0]:
                self.send_response(404); self.end_headers()
                self.wfile.write(b"cert not found")
                return

            # Resolve path + ตรวจอยู่ใน ROOT (กัน path traversal แม้ DB ถูก inject)
            pdf_path = (ROOT / row[0]).resolve()
            uploads_root = (ROOT / "uploads").resolve()
            if not str(pdf_path).startswith(str(uploads_root)):
                self.send_response(403); self.end_headers()
                self.wfile.write(b"path outside uploads")
                return
            if not pdf_path.exists():
                self.send_response(404); self.end_headers()
                self.wfile.write(b"file gone")
                return

            with open(pdf_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition",
                             f'inline; filename="cert_{course_id}.pdf"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(500); self.end_headers()
            self.wfile.write(f"Error: {e}".encode())

    def do_POST(self):
        if self.path == "/answer":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                params = parse_qs(body)

                job_id_short = params.get("job_id", [""])[0]
                course_id = params.get("course_id", [""])[0]
                n_questions = int(params.get("n_questions", ["0"])[0])

                # รวบรวมคำตอบ q0, q1, q2, ...
                answers = []
                for i in range(n_questions):
                    val = params.get(f"q{i}", [None])[0]
                    answers.append(int(val) if val is not None else 0)

                # หา full job_id จาก Redis key
                r = _redis.from_url(REDIS_URL, decode_responses=True)
                keys = r.keys(f"exam:human:*:{course_id}")
                answer_key = None
                for k in keys:
                    if ":answer:" not in k:
                        raw = r.get(k)
                        if raw:
                            d = json.loads(raw)
                            if d.get("job_id", "") == job_id_short:
                                # สร้าง answer key จาก pending key
                                answer_key = k.replace("exam:human:", "exam:human:answer:", 1)
                                break

                if answer_key:
                    answer_json = json.dumps(answers)
                    r.setex(answer_key, 60, answer_json)
                    # Publish notify worker ทันที (worker subscribe channel เดียวกัน)
                    # channel: exam:human:ch:{full_job_id}:{course_id} — สร้างจาก answer_key
                    channel = answer_key.replace("exam:human:answer:", "exam:human:ch:", 1)
                    try:
                        r.publish(channel, answer_json)
                    except Exception:
                        pass  # ถ้า publish fail worker จะ fallback poll answer_key
                    r.close()
                    # Redirect กลับหน้าหลัก
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                else:
                    r.close()
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"exam key not found")
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Error: {e}".encode())
        elif self.path == "/merge":
            self._do_merge()
        elif self.path == "/repair":
            self._do_repair()
        else:
            self.send_response(404)
            self.end_headers()

    def _do_merge(self):
        """Trigger merge_new_certs.py สำหรับ NID ที่กำหนด — รัน subprocess + reload หน้าหลัก"""
        import subprocess
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body)
            nid = (params.get("nid", [""])[0] or "").strip()
            days = (params.get("days", ["7"])[0] or "7").strip()
            if not nid.isdigit() or not days.isdigit():
                self.send_response(400); self.end_headers()
                self.wfile.write(b"invalid nid/days")
                return

            script = ROOT / "scripts" / "merge_new_certs.py"
            # ใช้ python.exe จาก venv ของโปรเจกต์
            py = ROOT / ".venv" / "Scripts" / "python.exe"
            if not py.exists():
                py = sys.executable  # fallback python ของระบบ
            proc = subprocess.run(
                [str(py), str(script), nid, "--days", days],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
            )
            ok = proc.returncode == 0
            log_tail = (proc.stdout or "")[-2000:] + "\n" + (proc.stderr or "")[-1000:]

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            color = "#a6e3a1" if ok else "#f38ba8"
            icon = "✅" if ok else "❌"
            self.wfile.write(f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Merge result</title>
<style>body{{background:#1e1e2e;color:#cdd6f4;font-family:'Segoe UI',sans-serif;padding:30px;}}
pre{{background:#181825;padding:16px;border-radius:8px;font-size:12px;max-height:400px;overflow:auto;}}
a{{color:#89b4fa;}}</style></head><body>
<h2 style="color:{color};">{icon} Merge {'สำเร็จ' if ok else 'ล้มเหลว'} — NID {nid}</h2>
<pre>{log_tail.replace('<','&lt;').replace('>','&gt;')}</pre>
<p><a href="/">← กลับหน้าหลัก</a></p>
<script>setTimeout(function(){{location.href='/';}}, 3000);</script>
</body></html>""".encode("utf-8"))
        except subprocess.TimeoutExpired:
            self.send_response(504); self.end_headers()
            self.wfile.write(b"merge timeout (>120s)")
        except Exception as e:
            self.send_response(500); self.end_headers()
            self.wfile.write(f"Error: {e}".encode())

    def _do_repair(self):
        """Trigger _repair_certs.py — รัน subprocess แบบ CLI args ไม่ต้องแก้ไฟล์มือ"""
        import subprocess
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = parse_qs(body)
            job_id = (params.get("job_id", [""])[0] or "").strip()
            nid    = (params.get("nid",    [""])[0] or "").strip()
            pwd    = (params.get("pwd",    [""])[0] or "").strip()
            courses= (params.get("courses",[""])[0] or "").strip()

            if not job_id or not nid or not pwd or not courses:
                self.send_response(400); self.end_headers()
                self.wfile.write(b"missing params"); return

            script = ROOT / "scripts" / "_repair_certs.py"
            py = ROOT / ".venv" / "Scripts" / "python.exe"
            if not py.exists():
                py = sys.executable

            env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(
                [str(py), str(script),
                 "--job-id", job_id,
                 "--nid", nid,
                 "--pwd", pwd,
                 "--courses", courses],
                cwd=str(ROOT),
                capture_output=True, text=True,
                timeout=300,
                encoding="utf-8", errors="replace",
                env=env,
            )
            ok = proc.returncode == 0
            log_out = (proc.stdout or "")[-3000:]
            log_err = (proc.stderr or "")[-1000:]
            log_tail = log_out + ("\n" + log_err if log_err.strip() else "")

            nid_disp = f"{nid[:4]}***{nid[-3:]}" if len(nid) >= 7 else nid
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            color = "#a6e3a1" if ok else "#f38ba8"
            icon = "✅" if ok else "❌"
            self.wfile.write(f"""<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>Repair result</title>
<style>body{{background:#1e1e2e;color:#cdd6f4;font-family:'Segoe UI',sans-serif;padding:30px;}}
pre{{background:#181825;padding:16px;border-radius:8px;font-size:12px;max-height:500px;overflow:auto;white-space:pre-wrap;}}
a{{color:#89b4fa;}}</style></head><body>
<h2 style="color:{color};">{icon} Repair {'สำเร็จ' if ok else 'ล้มเหลว'} — NID {nid_disp} &nbsp; คอร์ส {courses}</h2>
<pre>{log_tail.replace('<','&lt;').replace('>','&gt;')}</pre>
<p><a href="/">← กลับหน้าหลัก</a></p>
<script>setTimeout(function(){{location.href='/';}}, 5000);</script>
</body></html>""".encode("utf-8"))
        except subprocess.TimeoutExpired:
            self.send_response(504); self.end_headers()
            self.wfile.write(b"repair timeout (>300s)")
        except Exception as e:
            self.send_response(500); self.end_headers()
            self.wfile.write(f"Error: {e}".encode())

    def log_message(self, format, *args):
        pass  # ไม่ต้อง log requests


with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"🌐 Dashboard: http://localhost:{PORT}")
    httpd.serve_forever()
