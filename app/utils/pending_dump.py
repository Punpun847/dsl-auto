"""Record คำถามใหม่ที่เจอตอน automation รัน — ให้ user ทำเฉลยเพิ่มภายหลัง

Flow:
  1. ทุก attempt ของ _submit_exam — สำหรับ question ที่ไม่อยู่ใน cache
     → append เข้า pending_questions.jsonl (in tmp dir)
  2. User periodic run: `python scripts/answer_bank.py pending promote`
     → merge pending → questions/dump.json
     → ทำเฉลยผ่าน make_prompt + LLM (DeepSeek/Claude) + apply_answers ตามปกติ
"""
import hashlib
import json
import os
import tempfile
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Set

_TMP = Path(tempfile.gettempdir()) / "gyso_dsl"
_TMP.mkdir(parents=True, exist_ok=True)
PENDING_FILE = _TMP / "pending_questions.jsonl"

# Per-process in-memory dedup (กัน duplicate writes ใน worker session เดียว)
# Bounded LRU-style: เก็บ N hashes ล่าสุด — กัน memory leak ใน long-running worker
_SEEN_MAX = 10_000
_seen_hashes: Set[str] = set()
_seen_order: deque = deque(maxlen=_SEEN_MAX)
_lock = threading.Lock()


def _mark_seen(qh: str) -> None:
    """เพิ่ม hash ใหม่ + ถ้า set เต็มลบตัวเก่าสุดออก (LRU eviction)"""
    if len(_seen_order) >= _SEEN_MAX:
        old = _seen_order[0]  # ตัวที่จะถูก deque ลบเมื่อ append เกิน maxlen
        _seen_hashes.discard(old)
    _seen_order.append(qh)
    _seen_hashes.add(qh)


def question_hash(text: str) -> str:
    """ตรงกับ DSLClient._question_hash — SHA1 12 chars"""
    return hashlib.sha1(" ".join((text or "").split()).encode("utf-8")).hexdigest()[:12]


def record_questions(
    questions: List[Dict],
    cached_hashes: Set[str],
    course_id: str = "",
    exam_type: str = "",
) -> int:
    """Append คำถามที่ไม่อยู่ใน cache (และยังไม่เคย record ใน session นี้)

    Args:
      questions: [{q_text, options: [{value, text}]}]
      cached_hashes: set ของ q_hash ที่อยู่ใน Redis cache แล้ว
      course_id, exam_type: metadata

    Returns: จำนวนข้อใหม่ที่ append
    """
    if not questions:
        return 0

    new_records = []
    with _lock:
        for q in questions:
            qh = question_hash(q.get("q_text", ""))
            if not qh or qh in cached_hashes or qh in _seen_hashes:
                continue
            _mark_seen(qh)
            new_records.append({
                "q_hash": qh,
                "q_text": q.get("q_text"),
                "options": q.get("options", []),
                "course_id": course_id,
                "exam_type": exam_type,
                "first_seen_at": datetime.now(timezone.utc).isoformat(),
            })

    if not new_records:
        return 0

    # append jsonl (process-safe append on POSIX, OK on Windows too)
    try:
        with open(PENDING_FILE, "a", encoding="utf-8") as f:
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except Exception:
        return 0
    return len(new_records)


def read_pending() -> List[Dict]:
    """Read all pending questions, dedupe by q_hash, return list"""
    if not PENDING_FILE.exists():
        return []
    seen: Dict[str, Dict] = {}
    try:
        with open(PENDING_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                qh = r.get("q_hash")
                if qh and qh not in seen:
                    seen[qh] = r
    except Exception:
        return []
    return list(seen.values())


def clear_pending() -> int:
    """ลบไฟล์ pending (เรียกหลัง promote เสร็จ) — คืนจำนวนข้อที่ลบ"""
    if not PENDING_FILE.exists():
        return 0
    items = read_pending()
    try:
        PENDING_FILE.unlink()
    except Exception:
        pass
    # reset in-memory cache
    with _lock:
        _seen_hashes.clear()
        _seen_order.clear()
    return len(items)


def pending_count() -> int:
    """นับจำนวน unique q_hash ใน pending"""
    return len(read_pending())
