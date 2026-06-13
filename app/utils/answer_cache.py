"""Answer cache — Redis (primary) + file (backup) สำหรับเฉลย exam ที่เคยทำผ่าน

แยกออกจาก DSLClient เพื่อ:
  1. ลดขนาด god-class
  2. ทดสอบได้แยกจาก playwright
  3. ใช้งานได้จาก script อื่น (เช่น harvest_answers, import_answers) โดยไม่ต้อง instantiate browser
"""
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict

logger = logging.getLogger(__name__)

_TMP = Path(tempfile.gettempdir()) / "gyso_dsl"
_TMP.mkdir(parents=True, exist_ok=True)
ANSWER_CACHE_FILE = str(_TMP / "exam_answer_cache.json")

REDIS_KEY = "dsl:answer_cache"


import re as _re
# ตัดเลขข้อนำหน้า "3. " / "8) " / "10." — SET สุ่มสลับลำดับข้อ เลขเปลี่ยนแต่คำถามเดิม
_Q_NUM_PREFIX = _re.compile(r"^\s*\d{1,3}\s*[.)]\s*")


def question_hash(text: str) -> str:
    """SHA1 12 chars ของ question text
    normalize whitespace + ตัดเลขข้อนำหน้า (กัน hash เปลี่ยนเมื่อ SET สลับลำดับข้อ)"""
    stripped = _Q_NUM_PREFIX.sub("", text or "")
    normalized = " ".join(stripped.split())
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def load() -> Dict[str, str]:
    """โหลด cache — Redis ก่อน (shared across workers) → fallback file"""
    try:
        import redis as _sync_redis
        from app.config import settings as _s
        r = _sync_redis.from_url(_s.redis_url, decode_responses=True)
        data = r.hgetall(REDIS_KEY)
        r.close()
        if data:
            return data
    except Exception as e:
        logger.warning(f"redis cache load err: {e}")

    try:
        with open(ANSWER_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save(new_entries: Dict[str, str]) -> None:
    """Add ONLY new entries — กัน race ด้วยการ HSET เฉพาะ field ใหม่
    (ห้าม DELETE ทั้ง key แล้ว HSET mapping — workers อื่นจะหายไป)

    File backup เขียนจาก full Redis state เพื่อไม่ให้ local view ของ worker
    เดียวมา clobber state จริง
    """
    if not new_entries:
        return

    # 1. Redis primary — HSET เฉพาะ field ใหม่ (atomic per field)
    full_cache: Dict[str, str] = {}
    try:
        import redis as _sync_redis
        from app.config import settings as _s
        r = _sync_redis.from_url(_s.redis_url, decode_responses=True)
        r.hset(REDIS_KEY, mapping=new_entries)
        full_cache = r.hgetall(REDIS_KEY)
        r.close()
    except Exception as e:
        logger.warning(f"redis cache save err: {e}")

    # 2. File backup เฉพาะกรณีโหลด Redis state สำเร็จ — กัน clobber
    if not full_cache:
        return
    try:
        tmp_path = ANSWER_CACHE_FILE + f".tmp.{os.getpid()}"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(full_cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, ANSWER_CACHE_FILE)
    except Exception as e:
        logger.warning(f"file cache save err: {e}")
