"""GYSO Control Panel — http://localhost:9100

Visual pipeline สำหรับควบคุมระบบทั้งหมดในที่เดียว
- เห็น status ของ accounts.csv → API → Redis → Workers → DSL/SET → DB → Merge
- คลิก node ดูรายละเอียดและกดควบคุมได้

ไฟล์นี้เป็น UI layer ใหม่ — ไม่แก้ logic ใดๆ ของระบบเดิม
ทุก action เป็น subprocess wrapper ที่เรียก scripts/* ตัวเดิม
"""
import http.server
import json
import os
import socketserver
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ป้องกัน emoji ใน stdout บน Windows console (cp1252)
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import redis as _redis
from sqlalchemy import create_engine, text

ROOT = Path(__file__).parent.parent

# โหลด .env
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

# Config
_db_url = os.getenv("DATABASE_URL", "")
if _db_url.startswith("postgresql+asyncpg://"):
    _db_url = _db_url.replace("postgresql+asyncpg://", "postgresql://", 1)
DB = _db_url or "postgresql://gyso@localhost:5432/gyso_db"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PORT = int(os.getenv("CONTROL_PANEL_PORT", "9100"))
API_BASE = "http://127.0.0.1:8000"
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "9000"))
DASHBOARD_URL = f"http://localhost:{DASHBOARD_PORT}"

# Python ของ venv (ถ้ามี) — fallback ใช้ python ระบบ
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = VENV_PY if VENV_PY.exists() else Path(sys.executable)


# ═══════════════════════════════════════════════════════════════════════
# STATUS DETECTION (read-only)
# ═══════════════════════════════════════════════════════════════════════

def status_accounts():
    """อ่าน accounts.csv นับ rows + sample"""
    p = ROOT / "accounts.csv"
    if not p.exists():
        return {"status": "down", "rows": 0, "rows_with_hours": 0, "sample": [], "error": "ไม่พบไฟล์"}
    rows = []
    with_hours = 0
    total_hours = 0.0
    try:
        with open(p, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = [x.strip() for x in line.split(",")]
                if not parts[0]:
                    continue
                h = ""
                if len(parts) >= 3 and parts[2]:
                    h = parts[2]
                    with_hours += 1
                    try:
                        total_hours += float(h)
                    except ValueError:
                        pass
                rows.append({"nid": parts[0], "hours": h})
    except Exception as e:
        return {"status": "down", "rows": 0, "rows_with_hours": 0, "sample": [], "error": str(e)[:80]}

    sample = [
        {
            "nid": r["nid"],
            "hours": r["hours"] or "—",
        }
        for r in rows[:6]
    ]
    status = "up" if rows and with_hours == len(rows) else ("warn" if rows else "down")
    return {
        "status": status,
        "rows": len(rows),
        "rows_with_hours": with_hours,
        "total_hours": total_hours,
        "sample": sample,
    }


def status_api():
    """ตรวจ uvicorn บน port 8000"""
    try:
        import httpx
        r = httpx.get(f"{API_BASE}/openapi.json", timeout=1.0)
        return {"status": "up" if r.status_code == 200 else "warn", "code": r.status_code, "url": API_BASE}
    except Exception as e:
        return {"status": "down", "error": type(e).__name__, "url": API_BASE}


def status_redis_queue():
    """Redis: queue length + unacked"""
    try:
        r = _redis.from_url(REDIS_URL, decode_responses=True)
        queue_len = r.llen("celery")
        # unacked: keys ที่ขึ้นต้น "unacked"
        unacked_keys = r.keys("unacked*")
        unacked_count = 0
        for k in unacked_keys[:10]:
            try:
                t = r.type(k)
                if t == "hash":
                    unacked_count += r.hlen(k)
                elif t == "list":
                    unacked_count += r.llen(k)
                else:
                    unacked_count += 1
            except Exception:
                pass
        r.close()
        if unacked_count > 0:
            s = "warn"
        elif queue_len > 0:
            s = "busy"
        else:
            s = "up"
        return {"status": s, "queue_len": queue_len, "unacked": unacked_count}
    except Exception as e:
        return {"status": "down", "error": type(e).__name__}


def _list_celery_processes():
    """List running celery worker process command lines (Windows PowerShell)"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Process | "
             "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*celery*worker*' } | "
             "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        if not result.stdout.strip():
            return []
        data = json.loads(result.stdout)
        if isinstance(data, dict):
            data = [data]
        return data or []
    except Exception:
        return []


def status_workers():
    """Workers 1-4: process running + last log line"""
    procs = _list_celery_processes()
    now = datetime.now()
    workers = []
    for n in [1, 2, 3, 4]:
        is_running = any(f"worker{n}@" in (p.get("CommandLine") or "") for p in procs)
        log = ROOT / f"celery{n}.log"
        last_log = "-"
        log_age = None
        if log.exists():
            try:
                size = log.stat().st_size
                with open(log, "rb") as f:
                    f.seek(max(0, size - 8192))
                    tail = f.read().decode("utf-8", errors="replace").splitlines()
                # หาบรรทัดล่าสุดที่มีข้อความ
                for line in reversed(tail):
                    if line.strip():
                        last_log = line.strip()[:220]
                        break
                log_age = int((now - datetime.fromtimestamp(log.stat().st_mtime)).total_seconds())
            except Exception:
                pass
        workers.append({
            "n": n,
            "running": is_running,
            "last_log": last_log,
            "log_age_sec": log_age,
        })
    running = sum(1 for w in workers if w["running"])
    if running == 4:
        status = "up"
    elif running == 0:
        status = "down"
    else:
        status = "warn"
    return {"status": status, "running": running, "total": 4, "workers": workers}


def status_docker():
    """ตรวจ docker containers (postgres + redis)"""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return {"status": "down", "error": "docker daemon not running"}
        containers = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                c = json.loads(line)
                containers.append({"name": c.get("Names", "?"), "image": c.get("Image", ""), "status": c.get("Status", "")})
            except Exception:
                pass
        has_pg = any("postgres" in (c["name"] + c["image"]).lower() for c in containers)
        has_rd = any("redis" in (c["name"] + c["image"]).lower() for c in containers)
        if has_pg and has_rd:
            s = "up"
        elif has_pg or has_rd:
            s = "warn"
        else:
            s = "down"
        return {"status": s, "containers": containers, "has_postgres": has_pg, "has_redis": has_rd}
    except FileNotFoundError:
        return {"status": "down", "error": "docker CLI not installed"}
    except Exception as e:
        return {"status": "down", "error": type(e).__name__}


def status_db():
    """DB stats: jobs 1h, running, queued, done today, recent 5"""
    try:
        engine = create_engine(DB)
        with engine.connect() as c:
            jobs_1h = c.execute(text(
                "SELECT COUNT(*) FROM jobs WHERE created_at > NOW() - INTERVAL '1 hour'"
            )).scalar() or 0
            running = c.execute(text(
                "SELECT COUNT(*) FROM jobs WHERE status = 'running'"
            )).scalar() or 0
            queued = c.execute(text(
                "SELECT COUNT(*) FROM jobs WHERE status = 'queued'"
            )).scalar() or 0
            done_today = c.execute(text(
                "SELECT COUNT(*) FROM jobs WHERE status = 'done' AND completed_at > CURRENT_DATE"
            )).scalar() or 0
            recent_rows = c.execute(text(
                "SELECT id, status, total_hours, created_at, completed_at FROM jobs "
                "ORDER BY created_at DESC LIMIT 5"
            )).fetchall()
        recent = [
            {
                "id": str(r[0])[:8],
                "status": r[1],
                "hours": float(r[2]) if r[2] else None,
                "created": r[3].strftime("%H:%M:%S"),
                "completed": r[4].strftime("%H:%M:%S") if r[4] else None,
            }
            for r in recent_rows
        ]
        return {"status": "up", "jobs_1h": jobs_1h, "running": running, "queued": queued, "done_today": done_today, "recent": recent}
    except Exception as e:
        return {"status": "down", "error": str(e)[:80]}


def status_merge():
    """นับ PDF merged ใน certs/"""
    d = ROOT / "certs"
    if not d.exists():
        return {"status": "warn", "n_merged": 0, "recent": []}
    pdfs = sorted(d.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    recent = []
    for p in pdfs[:6]:
        recent.append({
            "name": p.name,
            "size_kb": p.stat().st_size // 1024,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
        })
    return {"status": "up", "n_merged": len(pdfs), "recent": recent}


def status_dsl_activity():
    """recent emoji status lines จาก worker logs (DSL/SET activity)"""
    EMO = "🚀✅❌📚🎯📤🏁🙋▶️⏳📑🔄🔑📋🎓"
    activities = []
    for n in [1, 2, 3, 4]:
        log = ROOT / f"celery{n}.log"
        if not log.exists():
            continue
        try:
            size = log.stat().st_size
            with open(log, "rb") as f:
                f.seek(max(0, size - 32768))
                tail = f.read().decode("utf-8", errors="replace").splitlines()
            picks = []
            for line in reversed(tail):
                if any(e in line for e in EMO):
                    picks.append(line.strip()[:200])
                    if len(picks) >= 3:
                        break
            if picks:
                activities.append({"worker": n, "lines": list(reversed(picks))})
        except Exception:
            pass
    return {"status": "up" if activities else "unknown", "activities": activities}


def status_pending_exams():
    """รอ human ตอบ (กระทบ workers)"""
    try:
        r = _redis.from_url(REDIS_URL, decode_responses=True)
        keys = r.keys("exam:human:*")
        n = 0
        items = []
        for k in keys:
            if ":answer:" in k:
                continue
            raw = r.get(k)
            if not raw:
                continue
            try:
                d = json.loads(raw)
                if d.get("expires_at", 0) > time.time():
                    n += 1
                    items.append({
                        "job_id": d.get("job_id", "?"),
                        "course_id": d.get("course_id", "?"),
                        "expires_in": int(d.get("expires_at", 0) - time.time()),
                    })
            except Exception:
                pass
        r.close()
        return {"status": "warn" if n else "up", "n_pending": n, "items": items[:5]}
    except Exception:
        return {"status": "unknown", "n_pending": 0, "items": []}


def collect_all_status():
    return {
        "ts": datetime.now().strftime("%H:%M:%S"),
        "accounts": status_accounts(),
        "api": status_api(),
        "docker": status_docker(),
        "redis": status_redis_queue(),
        "workers": status_workers(),
        "dsl": status_dsl_activity(),
        "db": status_db(),
        "merge": status_merge(),
        "pending": status_pending_exams(),
    }


# ═══════════════════════════════════════════════════════════════════════
# ACTIONS (subprocess wrappers — ไม่แก้ logic เดิม)
# ═══════════════════════════════════════════════════════════════════════

def _run_ps(ps_command: str, timeout: int = 30) -> dict:
    """รัน PowerShell, คืน {ok, stdout, stderr, code}"""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_command],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return {
            "ok": r.returncode == 0,
            "stdout": (r.stdout or "")[-3000:],
            "stderr": (r.stderr or "")[-1500:],
            "code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timeout ({timeout}s)", "code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": f"{type(e).__name__}: {e}", "code": -1}


def _run_py(script_relpath: str, args: list, timeout: int = 120) -> dict:
    """รัน Python script foreground, คืน output"""
    try:
        r = subprocess.run(
            [str(PY), str(ROOT / script_relpath), *args],
            cwd=str(ROOT), capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return {
            "ok": r.returncode == 0,
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-1500:],
            "code": r.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": f"timeout ({timeout}s)", "code": -1}
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": f"{type(e).__name__}: {e}", "code": -1}


def action_start_docker():
    return _run_ps("docker compose up -d", timeout=90)


def action_stop_docker():
    return _run_ps("docker compose down", timeout=60)


def action_start_api():
    cmd = (
        f"$env:PYTHONIOENCODING='utf-8'; "
        f"Start-Process -FilePath \"{PY}\" "
        f"-ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8000' "
        f"-WorkingDirectory \"{ROOT}\" -WindowStyle Hidden"
    )
    return _run_ps(cmd, timeout=15)


def action_start_workers():
    """Start 4 workers (--pool=solo)"""
    lines = ["$env:PYTHONIOENCODING='utf-8';"]
    for n in [1, 2, 3, 4]:
        lines.append(
            f"Start-Process -FilePath \"{PY}\" "
            f"-ArgumentList '-m','celery','-A','app.worker.celery_app','worker','--pool=solo','-n','worker{n}@%h','--logfile=celery{n}.log','--loglevel=info' "
            f"-WorkingDirectory \"{ROOT}\" -WindowStyle Hidden;"
        )
        lines.append("Start-Sleep -Milliseconds 500;")
    return _run_ps(" ".join(lines), timeout=20)


def action_stop_workers():
    cmd = (
        "$killed = @(); "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*celery*worker*' } | "
        "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force; $killed += $_.ProcessId } catch {} }; "
        "Write-Output ('Killed: ' + ($killed -join ','))"
    )
    return _run_ps(cmd, timeout=15)


def action_start_dashboard():
    dashboard_py = ROOT / "scripts" / "dashboard.py"
    cmd = (
        f"$env:PYTHONIOENCODING='utf-8'; "
        f"Start-Process -FilePath \"{PY}\" -ArgumentList \"{dashboard_py}\" "
        f"-WorkingDirectory \"{ROOT}\" -WindowStyle Hidden"
    )
    return _run_ps(cmd, timeout=10)


def action_start_all():
    """Start: docker → api → workers → dashboard (sequential)"""
    out = []
    r1 = action_start_docker()
    out.append(f"=== docker compose up ===\n{r1['stdout']}\n{r1['stderr']}")
    time.sleep(3)
    r2 = action_start_api()
    out.append(f"=== uvicorn (API) ===\n{r2['stdout']}\n{r2['stderr']}")
    time.sleep(2)
    r3 = action_start_workers()
    out.append(f"=== celery workers ===\n{r3['stdout']}\n{r3['stderr']}")
    time.sleep(2)
    r4 = action_start_dashboard()
    out.append(f"=== dashboard ===\n{r4['stdout']}\n{r4['stderr']}")
    overall = r1["ok"] and r2["ok"] and r3["ok"] and r4["ok"]
    return {"ok": overall, "stdout": "\n\n".join(out)[-5000:], "stderr": ""}


def action_stop_all_python():
    """Kill python processes ที่เกี่ยวกับระบบ (celery, uvicorn, dashboard.py)"""
    cmd = (
        "$killed = @(); "
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.Name -like 'python*' -and ("
        "$_.CommandLine -like '*celery*' -or "
        "$_.CommandLine -like '*uvicorn*' -or "
        "$_.CommandLine -like '*dashboard.py*'"
        ") } | "
        "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force; $killed += $_.ProcessId } catch {} }; "
        "Write-Output ('Killed: ' + ($killed -join ','))"
    )
    return _run_ps(cmd, timeout=15)


def action_stop_all():
    """Stop python + docker compose down"""
    r1 = action_stop_all_python()
    time.sleep(1)
    r2 = action_stop_docker()
    return {
        "ok": r1["ok"] and r2["ok"],
        "stdout": f"=== kill python ===\n{r1['stdout']}\n\n=== docker compose down ===\n{r2['stdout']}",
        "stderr": (r1["stderr"] or "") + "\n" + (r2["stderr"] or ""),
    }


def action_submit_csv():
    """รัน smart_submit.py accounts.csv (background — ใช้เวลานาน)"""
    cmd = (
        f"$env:PYTHONIOENCODING='utf-8'; "
        f"Start-Process -FilePath \"{PY}\" "
        f"-ArgumentList '{ROOT / 'scripts' / 'smart_submit.py'}','accounts.csv' "
        f"-WorkingDirectory \"{ROOT}\" -WindowStyle Hidden "
        f"-RedirectStandardOutput \"{ROOT / 'smart_submit.log'}\""
    )
    r = _run_ps(cmd, timeout=15)
    if r["ok"]:
        r["stdout"] = ("ส่งงาน background แล้ว — ดู progress ที่ smart_submit.log\n"
                       "(งานนี้ใช้เวลานาน เพราะต้อง login ทีละ user เพื่อ fetch courses)\n\n") + r["stdout"]
    return r


def action_submit_one(nid: str, pwd: str, hours: str):
    if not (nid and pwd and hours):
        return {"ok": False, "stdout": "", "stderr": "ต้องระบุ NID, PWD, HOURS"}
    if not nid.isdigit() or len(nid) != 13:
        return {"ok": False, "stdout": "", "stderr": "NID ต้อง 13 หลัก"}
    try:
        float(hours)
    except ValueError:
        return {"ok": False, "stdout": "", "stderr": "HOURS ต้องเป็นตัวเลข"}
    return _run_py("scripts/_submit_one.py", [nid, pwd, str(hours)], timeout=300)


def action_list_incomplete(nid: str, pwd: str):
    if not (nid and pwd):
        return {"ok": False, "stdout": "", "stderr": "ต้องระบุ NID, PWD"}
    if not nid.isdigit() or len(nid) != 13:
        return {"ok": False, "stdout": "", "stderr": "NID ต้อง 13 หลัก"}
    return _run_py("scripts/_list_incomplete.py", [nid, pwd], timeout=120)


def action_merge(nid: str, days: str):
    if not nid or not nid.isdigit():
        return {"ok": False, "stdout": "", "stderr": "NID ไม่ถูกต้อง"}
    if not days.isdigit():
        days = "7"
    return _run_py("scripts/merge_new_certs.py", [nid, "--days", days], timeout=180)


def action_fix_unacked():
    return _run_py("scripts/_fix_unacked.py", [], timeout=30)


# ═══════════════════════════════════════════════════════════════════════
# ROUTE MAP
# ═══════════════════════════════════════════════════════════════════════

ACTIONS = {
    "/start/all": ("start_all", action_start_all, 90),
    "/start/docker": ("start_docker", action_start_docker, 90),
    "/start/api": ("start_api", action_start_api, 20),
    "/start/workers": ("start_workers", action_start_workers, 20),
    "/start/dashboard": ("start_dashboard", action_start_dashboard, 15),
    "/stop/all": ("stop_all", action_stop_all, 30),
    "/stop/workers": ("stop_workers", action_stop_workers, 20),
    "/stop/docker": ("stop_docker", action_stop_docker, 60),
    "/submit/csv": ("submit_csv", action_submit_csv, 20),
    "/fix/unacked": ("fix_unacked", action_fix_unacked, 30),
}


# ═══════════════════════════════════════════════════════════════════════
# HTML / CSS / JS — pipeline UI
# ═══════════════════════════════════════════════════════════════════════

PAGE_HTML = r"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="utf-8">
<title>GYSO Control Panel</title>
<style>
  :root {
    --bg: #1e1e2e; --bg2: #181825; --bg3: #11111b;
    --surf: #313244; --surf2: #45475a;
    --text: #cdd6f4; --muted: #6c7086; --dim: #a6adc8;
    --blue: #89b4fa; --mauve: #cba6f7; --teal: #94e2d5;
    --green: #a6e3a1; --yellow: #f9e2af; --red: #f38ba8; --peach: #fab387;
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 20px 28px 60px; background: var(--bg); color: var(--text);
         font-family: 'Segoe UI', -apple-system, sans-serif; font-size: 14px; }
  h1 { color: var(--blue); margin: 0 0 4px; font-size: 24px; }
  .subtitle { color: var(--muted); font-size: 12px; margin-bottom: 18px; }
  .topbar { display: flex; gap: 10px; align-items: center; margin-bottom: 20px; flex-wrap: wrap; }
  .btn { background: var(--surf); color: var(--text); border: 1px solid var(--surf2);
         padding: 10px 18px; border-radius: 8px; cursor: pointer; font-size: 13px;
         font-weight: 600; transition: background 0.15s; font-family: inherit; }
  .btn:hover { background: var(--surf2); }
  .btn-primary { background: linear-gradient(135deg, var(--green), var(--teal)); color: var(--bg); border: none; }
  .btn-primary:hover { filter: brightness(1.1); }
  .btn-danger { background: var(--red); color: var(--bg); border: none; }
  .btn-danger:hover { filter: brightness(1.1); }
  .btn-warn { background: var(--yellow); color: var(--bg); border: none; }
  .btn-info { background: var(--blue); color: var(--bg); border: none; }
  .btn-sm { padding: 6px 12px; font-size: 12px; }
  .btn-ghost { background: transparent; border: 1px solid var(--surf2); color: var(--dim); }
  .btn-ghost:hover { color: var(--text); border-color: var(--mauve); }
  a.btn { text-decoration: none; display: inline-block; }

  .ts { color: var(--muted); font-size: 12px; margin-left: auto; }
  .ts .dot { display: inline-block; width: 8px; height: 8px; background: var(--green); border-radius: 50%; margin-right: 6px; animation: pulse 2s infinite; }
  @keyframes pulse { 50% { opacity: 0.4; } }

  /* Pipeline */
  .pipeline { display: flex; align-items: stretch; gap: 0; flex-wrap: wrap; margin: 12px 0 30px;
              background: var(--bg2); border: 1px solid var(--surf); border-radius: 14px;
              padding: 24px 18px; overflow-x: auto; }
  .node { flex: 0 0 130px; background: var(--bg3); border: 2px solid var(--surf); border-radius: 12px;
          padding: 14px 10px; text-align: center; cursor: pointer; position: relative;
          transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s; }
  .node:hover { transform: translateY(-3px); border-color: var(--mauve); box-shadow: 0 6px 20px rgba(203,166,247,0.15); }
  .node.active { border-color: var(--mauve); box-shadow: 0 0 0 3px rgba(203,166,247,0.25); }
  .node-icon { font-size: 28px; line-height: 1; margin-bottom: 6px; }
  .node-title { font-weight: 600; font-size: 12px; color: var(--text); margin-bottom: 4px; }
  .node-stat { font-size: 11px; color: var(--dim); min-height: 16px; }
  .node-badge { position: absolute; top: 8px; right: 8px; width: 12px; height: 12px;
                border-radius: 50%; background: var(--muted); border: 2px solid var(--bg3); }
  .status-up .node-badge { background: var(--green); box-shadow: 0 0 8px var(--green); }
  .status-warn .node-badge { background: var(--yellow); box-shadow: 0 0 8px var(--yellow); }
  .status-busy .node-badge { background: var(--blue); box-shadow: 0 0 8px var(--blue); }
  .status-down .node-badge { background: var(--red); box-shadow: 0 0 8px var(--red); animation: pulse 1.5s infinite; }

  .connector { flex: 0 0 36px; display: flex; align-items: center; justify-content: center;
               color: var(--surf2); font-size: 22px; user-select: none; }
  .connector.flow { color: var(--mauve); animation: flow 1.8s infinite; }
  @keyframes flow { 0%,100% { opacity: 0.3; } 50% { opacity: 1; transform: translateX(2px); } }

  /* Detail panels */
  .panels { margin-top: 18px; }
  .panel { background: var(--bg2); border: 1px solid var(--surf); border-radius: 12px;
           padding: 18px 22px; margin-bottom: 14px; display: none; }
  .panel.open { display: block; animation: slidein 0.2s; }
  @keyframes slidein { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: none; } }
  .panel h3 { margin: 0 0 12px; color: var(--mauve); font-size: 16px; display: flex; align-items: center; gap: 8px; }
  .panel h3 .close { margin-left: auto; cursor: pointer; color: var(--muted); font-size: 18px; }
  .panel h3 .close:hover { color: var(--red); }

  .grid { display: grid; gap: 10px; }
  .grid-3 { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
  .grid-4 { grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); }
  .stat-card { background: var(--bg3); padding: 10px 14px; border-radius: 8px; border-left: 3px solid var(--blue); }
  .stat-card .l { font-size: 10px; color: var(--muted); text-transform: uppercase; }
  .stat-card .v { font-size: 18px; font-weight: 700; color: var(--text); margin-top: 2px; }
  .stat-card.green { border-left-color: var(--green); }
  .stat-card.yellow { border-left-color: var(--yellow); }
  .stat-card.red { border-left-color: var(--red); }
  .stat-card.mauve { border-left-color: var(--mauve); }

  .worker-card { background: var(--bg3); padding: 10px 14px; border-radius: 8px; border-left: 3px solid var(--surf2);
                 display: flex; flex-direction: column; gap: 4px; }
  .worker-card.on { border-left-color: var(--green); }
  .worker-card.off { border-left-color: var(--red); }
  .worker-card .head { display: flex; justify-content: space-between; font-weight: 600; }
  .worker-card .log { font-size: 11px; color: var(--dim); font-family: monospace;
                       overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .age { font-size: 10px; color: var(--muted); }

  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; padding: 6px 8px; color: var(--muted); font-weight: 600; border-bottom: 1px solid var(--surf); }
  td { padding: 6px 8px; border-bottom: 1px solid var(--surf); }
  code { font-family: 'Cascadia Code', monospace; background: var(--bg3); padding: 1px 6px; border-radius: 3px; color: var(--teal); }

  form.inline { display: flex; gap: 8px; flex-wrap: wrap; align-items: end; margin-top: 8px; }
  form.inline label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; color: var(--muted); }
  form.inline input { background: var(--bg3); color: var(--text); border: 1px solid var(--surf);
                       border-radius: 6px; padding: 6px 10px; font-size: 13px; font-family: inherit; }
  form.inline input:focus { outline: none; border-color: var(--blue); }

  pre.out { background: var(--bg3); padding: 12px; border-radius: 8px; font-size: 11px;
            max-height: 280px; overflow: auto; white-space: pre-wrap; color: var(--dim); margin: 8px 0 0; }
  .err-line { color: var(--red); }
  .ok-line { color: var(--green); }

  .actions-row { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }

  /* Modal */
  .modal { position: fixed; inset: 0; background: rgba(0,0,0,0.7); display: none;
           align-items: center; justify-content: center; z-index: 100; }
  .modal.open { display: flex; }
  .modal-box { background: var(--bg2); border: 2px solid var(--mauve); border-radius: 12px;
               padding: 24px; max-width: 480px; min-width: 320px; }
  .modal-box h3 { margin: 0 0 12px; color: var(--yellow); }
  .modal-box p { margin: 0 0 18px; line-height: 1.5; }
  .modal-actions { display: flex; gap: 10px; justify-content: flex-end; }

  /* Toast */
  .toast { position: fixed; bottom: 24px; right: 24px; background: var(--bg2);
           border-left: 4px solid var(--green); padding: 12px 18px; border-radius: 8px;
           box-shadow: 0 6px 24px rgba(0,0,0,0.4); display: none; max-width: 380px;
           font-size: 13px; z-index: 90; }
  .toast.open { display: block; animation: slidein 0.25s; }
  .toast.err { border-left-color: var(--red); }
  .toast.info { border-left-color: var(--blue); }

  /* Spinner */
  .spin { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--surf);
          border-top-color: var(--blue); border-radius: 50%; animation: spin 0.7s linear infinite;
          vertical-align: middle; margin-right: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .loading { opacity: 0.6; pointer-events: none; }

  .legend { display: flex; gap: 14px; font-size: 11px; color: var(--muted); margin-top: 4px; }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend .d { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
</style>
</head>
<body>

<h1>🎛️ GYSO Control Panel</h1>
<div class="subtitle">ระบบ e-learning กยศ. (DSL→SSO→SET) — คลิก node เพื่อดูรายละเอียดและควบคุม</div>

<div class="topbar">
  <button class="btn btn-primary" onclick="confirmAct('/start/all','▶ Start All Services','เปิดทุกอย่างตามลำดับ: Docker → API → Workers → Dashboard')">▶ Start All</button>
  <button class="btn btn-danger" onclick="confirmAct('/stop/all','⏹ Stop All Services','หยุดทุกอย่างและ docker compose down — งานที่กำลังรันจะถูก kill')">⏹ Stop All</button>
  <a href="http://localhost:DASHBOARD_PORT_TOKEN" target="_blank" class="btn btn-ghost">📊 Dashboard</a>
  <a href="API_BASE_TOKEN/docs" target="_blank" class="btn btn-ghost">📘 API docs</a>
  <button class="btn btn-ghost btn-sm" onclick="loadStatus({includePanels:true})">🔄 Refresh</button>
  <span class="ts"><span class="dot"></span><span id="ts">--:--:--</span></span>
</div>

<div class="legend">
  <span><span class="d" style="background:var(--green)"></span>up</span>
  <span><span class="d" style="background:var(--blue)"></span>busy / มีคิว</span>
  <span><span class="d" style="background:var(--yellow)"></span>warn (เช่น 2/4 workers)</span>
  <span><span class="d" style="background:var(--red)"></span>down</span>
  <span><span class="d" style="background:var(--muted)"></span>unknown</span>
</div>

<section class="pipeline" id="pipeline">
  <div class="node" data-node="accounts" onclick="togglePanel('accounts')">
    <span class="node-badge"></span>
    <div class="node-icon">📁</div>
    <div class="node-title">accounts.csv</div>
    <div class="node-stat" data-stat="accounts">—</div>
  </div>
  <div class="connector flow">▶</div>

  <div class="node" data-node="submit" onclick="togglePanel('submit')">
    <span class="node-badge"></span>
    <div class="node-icon">🚀</div>
    <div class="node-title">Submit Job</div>
    <div class="node-stat" data-stat="submit">—</div>
  </div>
  <div class="connector flow">▶</div>

  <div class="node" data-node="api" onclick="togglePanel('api')">
    <span class="node-badge"></span>
    <div class="node-icon">⚙️</div>
    <div class="node-title">API :8000</div>
    <div class="node-stat" data-stat="api">—</div>
  </div>
  <div class="connector flow">▶</div>

  <div class="node" data-node="redis" onclick="togglePanel('redis')">
    <span class="node-badge"></span>
    <div class="node-icon">📨</div>
    <div class="node-title">Redis Queue</div>
    <div class="node-stat" data-stat="redis">—</div>
  </div>
  <div class="connector flow">▶</div>

  <div class="node" data-node="workers" onclick="togglePanel('workers')">
    <span class="node-badge"></span>
    <div class="node-icon">👷</div>
    <div class="node-title">Workers 1-4</div>
    <div class="node-stat" data-stat="workers">—</div>
  </div>
  <div class="connector flow">▶</div>

  <div class="node" data-node="dsl" onclick="togglePanel('dsl')">
    <span class="node-badge"></span>
    <div class="node-icon">🌐</div>
    <div class="node-title">DSL → SET</div>
    <div class="node-stat" data-stat="dsl">—</div>
  </div>
  <div class="connector flow">▶</div>

  <div class="node" data-node="db" onclick="togglePanel('db')">
    <span class="node-badge"></span>
    <div class="node-icon">🗄️</div>
    <div class="node-title">DB (Postgres)</div>
    <div class="node-stat" data-stat="db">—</div>
  </div>
  <div class="connector flow">▶</div>

  <div class="node" data-node="merge" onclick="togglePanel('merge')">
    <span class="node-badge"></span>
    <div class="node-icon">📑</div>
    <div class="node-title">Merge PDF</div>
    <div class="node-stat" data-stat="merge">—</div>
  </div>

  <div class="connector" style="flex:0 0 18px;"></div>

  <div class="node" data-node="docker" onclick="togglePanel('docker')" style="background:#1f1d2e;">
    <span class="node-badge"></span>
    <div class="node-icon">🐳</div>
    <div class="node-title">Docker</div>
    <div class="node-stat" data-stat="docker">—</div>
  </div>
</section>

<section class="panels" id="panels"></section>

<div class="modal" id="modal">
  <div class="modal-box">
    <h3 id="modal-title">⚠️ ยืนยัน</h3>
    <p id="modal-msg"></p>
    <div class="modal-actions">
      <button class="btn btn-ghost" onclick="modalCancel()">ยกเลิก</button>
      <button class="btn btn-danger" id="modal-ok" onclick="modalOk()">ยืนยัน</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
let LAST = {};
let paused = false;
let refreshTimer = null;

// === panels content (เรนเดอร์ฝั่ง client จาก LAST) ===
// เก็บค่า input/output ก่อน rebuild แล้ว restore กลับ — กันที่พิมไว้หาย
function renderPanels() {
  const root = $('#panels');
  const savedInputs = {};
  root.querySelectorAll('input,textarea').forEach(el => {
    if (el.id) savedInputs[el.id] = el.value;
  });
  const savedOuts = {};
  root.querySelectorAll('pre.out').forEach(el => {
    if (el.id) savedOuts[el.id] = {text: el.textContent, show: el.style.display};
  });
  const focusedId = document.activeElement && document.activeElement.id;
  const focusedSelStart = (document.activeElement && 'selectionStart' in document.activeElement) ? document.activeElement.selectionStart : null;
  const scrollY = window.scrollY;

  root.innerHTML = '';
  for (const key of ['accounts','submit','api','redis','workers','dsl','db','merge','docker']) {
    const open = root.dataset[key] === 'open';
    const html = panelHTML(key);
    const div = document.createElement('div');
    div.className = 'panel' + (open ? ' open' : '');
    div.dataset.panel = key;
    div.innerHTML = html;
    root.appendChild(div);
  }

  for (const id in savedInputs) {
    const el = document.getElementById(id);
    if (el && savedInputs[id] !== '') el.value = savedInputs[id];
  }
  for (const id in savedOuts) {
    const el = document.getElementById(id);
    if (el && savedOuts[id].text) {
      el.textContent = savedOuts[id].text;
      el.style.display = savedOuts[id].show || 'block';
    }
  }
  if (focusedId) {
    const el = document.getElementById(focusedId);
    if (el && el.focus) {
      el.focus();
      if (focusedSelStart !== null && 'setSelectionRange' in el) {
        try { el.setSelectionRange(focusedSelStart, focusedSelStart); } catch(e) {}
      }
    }
  }
  window.scrollTo(0, scrollY);
}

function panelHTML(key) {
  const d = LAST[key] || {};
  const closeBtn = `<span class="close" onclick="togglePanel('${key}')">✕</span>`;
  if (key === 'accounts') {
    const rows = (d.sample || []).map(r => `<tr><td><code>${r.nid}</code></td><td>${r.hours} ชม.</td></tr>`).join('');
    return `<h3>📁 accounts.csv ${closeBtn}</h3>
      <div class="grid grid-4">
        <div class="stat-card"><div class="l">Rows</div><div class="v">${d.rows ?? '-'}</div></div>
        <div class="stat-card green"><div class="l">มีชั่วโมง</div><div class="v">${d.rows_with_hours ?? '-'}</div></div>
        <div class="stat-card mauve"><div class="l">รวมชั่วโมง</div><div class="v">${(d.total_hours||0).toFixed(0)}</div></div>
      </div>
      <p style="color:var(--muted);font-size:12px;margin:14px 0 4px;">ตัวอย่าง 6 แถวแรก (NID มาส์ก):</p>
      <table><thead><tr><th>NID</th><th>ชั่วโมง</th></tr></thead><tbody>${rows || '<tr><td colspan=2 style="color:var(--muted)">ไม่มี</td></tr>'}</tbody></table>
      <p style="color:var(--muted);font-size:11px;margin-top:10px;">📂 path: <code>${'accounts.csv'}</code> — แก้ไฟล์ตรงๆ ที่ project root</p>
      ${d.error ? `<p class="err-line">⚠️ ${d.error}</p>` : ''}`;
  }
  if (key === 'submit') {
    return `<h3>🚀 Submit Job ${closeBtn}</h3>
      <p style="color:var(--dim);font-size:12px;margin:0 0 12px;">ส่งงานเข้าระบบ — API ต้อง up ก่อน</p>
      <div class="actions-row">
        <button class="btn btn-primary" onclick="confirmAct('/submit/csv','📤 Submit accounts.csv ทั้งไฟล์','ระบบจะ login ทีละ user เพื่อ fetch courses + submit job — รันใน background, ดู smart_submit.log')">📤 Submit accounts.csv ทั้งไฟล์</button>
      </div>
      <h4 style="color:var(--dim);margin:18px 0 8px;font-size:13px;">หรือส่ง user คนเดียว:</h4>
      <form class="inline" onsubmit="event.preventDefault(); submitOne();">
        <label>NID (13 หลัก)<input id="s-nid" type="text" maxlength="13" pattern="\\d{13}" required></label>
        <label>Password<input id="s-pwd" type="password" required></label>
        <label>Hours<input id="s-hr" type="number" step="0.5" min="1" max="50" value="18" required></label>
        <button type="submit" class="btn btn-info">📤 Submit คนเดียว</button>
        <button type="button" class="btn btn-ghost" onclick="listIncomplete()">📋 ดู courses ที่ทำได้ก่อน</button>
      </form>
      <pre class="out" id="submit-out" style="display:none"></pre>`;
  }
  if (key === 'api') {
    return `<h3>⚙️ API (uvicorn) ${closeBtn}</h3>
      <div class="grid grid-3">
        <div class="stat-card ${d.status==='up'?'green':'red'}"><div class="l">Status</div><div class="v">${d.status || '?'}</div></div>
        <div class="stat-card"><div class="l">HTTP code</div><div class="v">${d.code || '-'}</div></div>
        <div class="stat-card mauve"><div class="l">URL</div><div class="v" style="font-size:12px;font-family:monospace;">${d.url || '-'}</div></div>
      </div>
      <div class="actions-row">
        <button class="btn btn-primary" onclick="confirmAct('/start/api','▶ Start API','เปิด uvicorn process ใหม่ — ถ้า API up อยู่แล้วอาจชน port')">▶ Start</button>
        <a href="${d.url || '#'}/docs" target="_blank" class="btn btn-ghost">📘 OpenAPI docs</a>
      </div>
      ${d.error ? `<p class="err-line">⚠️ ${d.error}</p>` : ''}`;
  }
  if (key === 'redis') {
    return `<h3>📨 Redis Queue ${closeBtn}</h3>
      <div class="grid grid-3">
        <div class="stat-card ${d.queue_len>0?'mauve':'green'}"><div class="l">Queue (celery)</div><div class="v">${d.queue_len ?? '-'}</div></div>
        <div class="stat-card ${d.unacked>0?'yellow':'green'}"><div class="l">Unacked</div><div class="v">${d.unacked ?? '-'}</div></div>
      </div>
      <p style="color:var(--muted);font-size:12px;margin-top:10px;">ถ้า unacked > 0 แสดงว่ามี task ติด — รัน Fix unacked เพื่อกู้</p>
      <div class="actions-row">
        <button class="btn btn-warn" onclick="confirmAct('/fix/unacked','🔧 Fix unacked tasks','กู้ task ที่ติดใน Redis unacked queue')">🔧 Fix Unacked</button>
      </div>
      ${d.error ? `<p class="err-line">⚠️ ${d.error}</p>` : ''}`;
  }
  if (key === 'workers') {
    const list = (d.workers||[]).map(w => `
      <div class="worker-card ${w.running?'on':'off'}">
        <div class="head"><span>👷 worker${w.n}</span><span style="color:${w.running?'var(--green)':'var(--red)'}">${w.running?'● running':'○ down'}</span></div>
        <div class="log" title="${(w.last_log||'').replace(/"/g,'&quot;')}">${w.last_log || '-'}</div>
        ${w.log_age_sec!=null ? `<div class="age">log ${formatAge(w.log_age_sec)} ago</div>` : ''}
      </div>`).join('');
    return `<h3>👷 Workers ${closeBtn}</h3>
      <div class="grid grid-3">
        <div class="stat-card ${d.running===4?'green':d.running===0?'red':'yellow'}"><div class="l">Running</div><div class="v">${d.running ?? '-'}/${d.total ?? 4}</div></div>
      </div>
      <div class="grid grid-3" style="margin-top:12px;">${list}</div>
      <div class="actions-row">
        <button class="btn btn-primary" onclick="confirmAct('/start/workers','▶ Start Workers','เปิด 4 workers ใหม่ — ถ้ามี workers รันอยู่แล้วอาจชน')">▶ Start 4 Workers</button>
        <button class="btn btn-danger" onclick="confirmAct('/stop/workers','⏹ Stop Workers','kill workers ทั้งหมด — task ที่ทำอยู่จะถูก interrupt')">⏹ Stop All</button>
      </div>`;
  }
  if (key === 'dsl') {
    const act = (d.activities||[]).map(a => `
      <div class="worker-card on">
        <div class="head"><span>worker${a.worker}</span></div>
        ${a.lines.map(l => `<div class="log" title="${l.replace(/"/g,'&quot;')}">${l}</div>`).join('')}
      </div>`).join('');
    return `<h3>🌐 DSL → SET (browser activity) ${closeBtn}</h3>
      <p style="color:var(--muted);font-size:12px;margin:0 0 10px;">บรรทัด log ล่าสุดที่มี emoji status (3 บรรทัดต่อ worker)</p>
      ${act || '<p style="color:var(--muted)">ไม่มี activity</p>'}
      ${d.n_pending > 0 ? `<p style="color:var(--red);margin-top:14px;">🙋 รอ human ตอบ ${d.n_pending} รายการ — ไปตอบที่ <a href="http://localhost:DASHBOARD_PORT_TOKEN" target="_blank" style="color:var(--blue)">Dashboard</a></p>` : ''}`;
  }
  if (key === 'db') {
    const recent = (d.recent||[]).map(r => `<tr><td><code>${r.id}</code></td><td><span style="color:${statusColor(r.status)}">${r.status}</span></td><td>${r.hours?r.hours+' ชม.':'-'}</td><td style="color:var(--muted)">${r.created}</td></tr>`).join('');
    return `<h3>🗄️ Database (PostgreSQL) ${closeBtn}</h3>
      <div class="grid grid-4">
        <div class="stat-card"><div class="l">Jobs (1h)</div><div class="v">${d.jobs_1h ?? '-'}</div></div>
        <div class="stat-card yellow"><div class="l">Running</div><div class="v">${d.running ?? '-'}</div></div>
        <div class="stat-card"><div class="l">Queued</div><div class="v">${d.queued ?? '-'}</div></div>
        <div class="stat-card green"><div class="l">Done วันนี้</div><div class="v">${d.done_today ?? '-'}</div></div>
      </div>
      <p style="color:var(--muted);font-size:12px;margin:14px 0 4px;">Jobs ล่าสุด 5 ตัว:</p>
      <table><thead><tr><th>ID</th><th>Status</th><th>Hours</th><th>Created</th></tr></thead><tbody>${recent || '<tr><td colspan=4 style="color:var(--muted)">ไม่มี</td></tr>'}</tbody></table>
      <div class="actions-row">
        <a href="http://localhost:DASHBOARD_PORT_TOKEN" target="_blank" class="btn btn-info">📊 ดู Dashboard เต็ม</a>
      </div>
      ${d.error ? `<p class="err-line">⚠️ ${d.error}</p>` : ''}`;
  }
  if (key === 'merge') {
    const recent = (d.recent||[]).map(r => `<tr><td>${r.name}</td><td>${r.size_kb} KB</td><td style="color:var(--muted)">${r.mtime}</td></tr>`).join('');
    return `<h3>📑 Merge PDF ${closeBtn}</h3>
      <div class="grid grid-3">
        <div class="stat-card green"><div class="l">Merged PDFs</div><div class="v">${d.n_merged ?? '-'}</div></div>
      </div>
      <p style="color:var(--muted);font-size:12px;margin:14px 0 4px;">ไฟล์ล่าสุดใน <code>certs/</code>:</p>
      <table><thead><tr><th>ชื่อไฟล์</th><th>ขนาด</th><th>เวลา</th></tr></thead><tbody>${recent || '<tr><td colspan=3 style="color:var(--muted)">ยังไม่มี</td></tr>'}</tbody></table>
      <h4 style="color:var(--dim);margin:18px 0 8px;font-size:13px;">Merge cert ของ user คนใดคนหนึ่ง:</h4>
      <form class="inline" onsubmit="event.preventDefault(); doMerge();">
        <label>NID<input id="m-nid" type="text" maxlength="13" pattern="\\d{13}" required></label>
        <label>Days<input id="m-days" type="number" min="1" max="90" value="7" required></label>
        <button type="submit" class="btn btn-primary">📑 Merge ตอนนี้</button>
      </form>
      <pre class="out" id="merge-out" style="display:none"></pre>`;
  }
  if (key === 'docker') {
    const list = (d.containers||[]).map(c => `<tr><td>${c.name}</td><td><code style="font-size:10px;">${c.image}</code></td><td style="color:var(--green);">${c.status}</td></tr>`).join('');
    return `<h3>🐳 Docker (PostgreSQL + Redis) ${closeBtn}</h3>
      <div class="grid grid-3">
        <div class="stat-card ${d.has_postgres?'green':'red'}"><div class="l">postgres</div><div class="v">${d.has_postgres?'● up':'○ down'}</div></div>
        <div class="stat-card ${d.has_redis?'green':'red'}"><div class="l">redis</div><div class="v">${d.has_redis?'● up':'○ down'}</div></div>
      </div>
      ${list ? `<p style="color:var(--muted);font-size:12px;margin:14px 0 4px;">Containers:</p>
        <table><thead><tr><th>ชื่อ</th><th>Image</th><th>Status</th></tr></thead><tbody>${list}</tbody></table>` : ''}
      <div class="actions-row">
        <button class="btn btn-primary" onclick="confirmAct('/start/docker','▶ docker compose up -d','เปิด postgres + redis containers')">▶ Start</button>
        <button class="btn btn-danger" onclick="confirmAct('/stop/docker','⏹ docker compose down','หยุด containers — data ยังอยู่ใน volume')">⏹ Stop</button>
      </div>
      ${d.error ? `<p class="err-line">⚠️ ${d.error}</p>` : ''}`;
  }
  return `<h3>${key}</h3><pre>${JSON.stringify(d,null,2)}</pre>`;
}

function statusColor(s) {
  if (s === 'done') return 'var(--green)';
  if (s === 'running') return 'var(--yellow)';
  if (s === 'failed') return 'var(--red)';
  if (s === 'queued') return 'var(--blue)';
  return 'var(--muted)';
}
function formatAge(s) {
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm';
  return Math.floor(s/3600) + 'h ' + Math.floor((s%3600)/60) + 'm';
}

function togglePanel(key) {
  const root = $('#panels');
  const cur = root.dataset[key] === 'open';
  root.dataset[key] = cur ? '' : 'open';
  $$('.node').forEach(n => n.classList.remove('active'));
  if (!cur) {
    const node = document.querySelector(`.node[data-node="${key}"]`);
    if (node) node.classList.add('active');
    paused = true;
  } else {
    paused = false;
  }
  renderPanels();
}

// === status load ===
async function loadStatus(opts) {
  opts = opts || {};
  try {
    const r = await fetch('/api/status');
    LAST = await r.json();
    updateNodes();
    // rebuild panels เฉพาะตอน user สั่ง refresh เอง หรือหลัง action จบ
    // ตอน auto-refresh จากเวลา 5s ไม่ rebuild — เก็บ form input ที่ user พิมไว้
    if (opts.includePanels) renderPanels();
    $('#ts').textContent = LAST.ts || new Date().toLocaleTimeString();
  } catch (e) {
    console.error(e);
    showToast('โหลด status ไม่ได้: ' + e.message, 'err');
  }
}

function updateNodes() {
  for (const key of ['accounts','api','redis','workers','dsl','db','merge','docker','submit']) {
    const node = document.querySelector(`.node[data-node="${key}"]`);
    if (!node) continue;
    let status = 'unknown';
    let stat = '—';
    const d = LAST[key];
    if (key === 'accounts' && d) { status = d.status; stat = `${d.rows} rows (${d.rows_with_hours} ok)`; }
    else if (key === 'api' && d) { status = d.status; stat = d.status === 'up' ? '🟢 UP' : (d.error || 'down'); }
    else if (key === 'redis' && d) { status = d.status; stat = `Q: ${d.queue_len} / U: ${d.unacked}`; }
    else if (key === 'workers' && d) { status = d.status; stat = `${d.running}/${d.total}`; }
    else if (key === 'dsl' && d) {
      const totalActive = (d.activities||[]).length;
      const pending = LAST.pending ? LAST.pending.n_pending : 0;
      status = pending > 0 ? 'warn' : (totalActive ? 'up' : 'unknown');
      stat = pending > 0 ? `🙋 รอตอบ ${pending}` : (totalActive ? `${totalActive} active` : 'idle');
    }
    else if (key === 'db' && d) { status = d.status; stat = `${d.jobs_1h} jobs (1h)`; }
    else if (key === 'merge' && d) { status = d.status; stat = `${d.n_merged} PDFs`; }
    else if (key === 'docker' && d) { status = d.status; stat = (d.has_postgres?'pg ':'')+(d.has_redis?'rd':'') || 'down'; }
    else if (key === 'submit') {
      const apiUp = LAST.api?.status === 'up';
      const accOk = LAST.accounts?.rows_with_hours > 0;
      status = apiUp && accOk ? 'up' : 'warn';
      stat = apiUp ? (accOk ? 'พร้อมส่ง' : 'accounts.csv ว่าง') : 'API down';
    }
    // apply class
    node.className = 'node status-' + status + (node.classList.contains('active') ? ' active' : '');
    const ss = node.querySelector('[data-stat]');
    if (ss) ss.textContent = stat;
  }
}

// === actions ===
let pendingAct = null;
function confirmAct(path, title, msg) {
  pendingAct = path;
  $('#modal-title').textContent = title;
  $('#modal-msg').textContent = msg;
  $('#modal').classList.add('open');
  paused = true;
}
function modalCancel() {
  pendingAct = null;
  $('#modal').classList.remove('open');
}
async function modalOk() {
  const path = pendingAct;
  pendingAct = null;
  $('#modal').classList.remove('open');
  if (!path) return;
  await runAction(path);
}
async function runAction(path, body) {
  showToast('⏳ กำลังรัน ' + path + ' ...', 'info', 0);
  try {
    const opts = {method: 'POST'};
    if (body) {
      opts.headers = {'Content-Type': 'application/x-www-form-urlencoded'};
      opts.body = new URLSearchParams(body).toString();
    }
    const r = await fetch(path, opts);
    const data = await r.json();
    const ok = data.ok !== false;
    showToast((ok ? '✅' : '❌') + ' ' + path + (data.stderr ? ' — ' + data.stderr.slice(0,80) : ''), ok?'':'err', 4000);
    // โชว์ output ใน panel ที่เกี่ยวข้อง
    showOutput(path, data);
    await sleep(800);
    await loadStatus({includePanels: true});
  } catch (e) {
    showToast('❌ ' + e.message, 'err', 4000);
  }
}

function showOutput(path, data) {
  let target = null;
  if (path.startsWith('/submit')) target = $('#submit-out');
  else if (path.startsWith('/merge')) target = $('#merge-out');
  else if (path.startsWith('/list_incomplete')) target = $('#submit-out');
  if (target) {
    target.style.display = 'block';
    target.textContent = (data.stdout || '') + (data.stderr ? '\n[stderr]\n' + data.stderr : '');
  }
}

async function submitOne() {
  const nid = $('#s-nid').value.trim();
  const pwd = $('#s-pwd').value;
  const hours = $('#s-hr').value;
  if (!/^\d{13}$/.test(nid)) { showToast('NID ต้อง 13 หลัก', 'err', 3000); return; }
  pendingAct = '__submit_one__';
  $('#modal-title').textContent = '📤 Submit user คนเดียว';
  $('#modal-msg').textContent = `จะ submit งานสำหรับ NID ${nid} (${hours} ชม.) — รัน foreground ใช้เวลาประมาณ 1-3 นาที`;
  $('#modal').classList.add('open');
  $('#modal-ok').onclick = async () => {
    $('#modal').classList.remove('open');
    $('#modal-ok').onclick = modalOk;
    await runAction('/submit/one', {nid, pwd, hours});
  };
}

async function listIncomplete() {
  const nid = $('#s-nid').value.trim();
  const pwd = $('#s-pwd').value;
  if (!/^\d{13}$/.test(nid)) { showToast('NID ต้อง 13 หลัก', 'err', 3000); return; }
  if (!pwd) { showToast('ใส่ password ก่อน', 'err', 3000); return; }
  await runAction('/list_incomplete', {nid, pwd});
}

async function doMerge() {
  const nid = $('#m-nid').value.trim();
  const days = $('#m-days').value || '7';
  if (!/^\d{13}$/.test(nid)) { showToast('NID ต้อง 13 หลัก', 'err', 3000); return; }
  await runAction('/merge', {nid, days});
}

// === toast ===
let toastT = null;
function showToast(msg, kind, ms) {
  const t = $('#toast');
  t.className = 'toast open ' + (kind || '');
  t.textContent = msg;
  if (toastT) clearTimeout(toastT);
  if (ms) {
    toastT = setTimeout(() => t.classList.remove('open'), ms);
  }
}
function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// === refresh loop ===
function startRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    if (!paused) loadStatus();
  }, 5000);
}

// === keyboard close modal ===
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if ($('#modal').classList.contains('open')) modalCancel();
    else $$('.panel.open').forEach(p => togglePanel(p.dataset.panel));
  }
});

// init
loadStatus();
startRefresh();
</script>
</body></html>
"""


def render_page() -> str:
    return (PAGE_HTML
            .replace("DASHBOARD_PORT_TOKEN", str(DASHBOARD_PORT))
            .replace("API_BASE_TOKEN", API_BASE))


# ═══════════════════════════════════════════════════════════════════════
# HTTP HANDLER
# ═══════════════════════════════════════════════════════════════════════

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_html(render_page())
        elif path == "/api/status":
            try:
                data = collect_all_status()
                self._send_json(data)
            except Exception as e:
                self._send_json({"error": str(e)}, code=500)
        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            params = parse_qs(raw) if raw else {}

            if path in ACTIONS:
                _, fn, _ = ACTIONS[path]
                result = fn()
            elif path == "/submit/one":
                result = action_submit_one(
                    params.get("nid", [""])[0],
                    params.get("pwd", [""])[0],
                    params.get("hours", ["18"])[0],
                )
            elif path == "/merge":
                result = action_merge(
                    params.get("nid", [""])[0],
                    params.get("days", ["7"])[0],
                )
            elif path == "/list_incomplete":
                result = action_list_incomplete(
                    params.get("nid", [""])[0],
                    params.get("pwd", [""])[0],
                )
            else:
                self.send_response(404); self.end_headers(); return

            self._send_json(result)
        except Exception as e:
            self._send_json({"ok": False, "stdout": "", "stderr": f"{type(e).__name__}: {e}"}, code=500)

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: dict, code: int = 200):
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args, **kwargs):
        return  # quiet


class ThreadedServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == "__main__":
    print(f"🎛️  Control Panel: http://localhost:{PORT}")
    print(f"📊 Dashboard:      {DASHBOARD_URL}")
    print(f"⚙️  API:            {API_BASE}")
    print(f"🐍 Python:         {PY}")
    print(f"📂 Project root:   {ROOT}")
    print()
    with ThreadedServer(("127.0.0.1", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n👋 หยุด control panel")
