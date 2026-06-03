"""NID registry — สะสม {sha256(nid): nid} ให้ dashboard reverse hash กลับเป็น NID ได้

ทำไมต้องมี: DB เก็บแค่ nid_hash (SHA-256, ทางเดียว) เพื่อ PII protection.
Dashboard ต้อง map hash กลับเป็น NID จริงเพื่อแสดงผล — เดิมพึ่ง accounts.csv อย่างเดียว
ซึ่งเป็น batch ชั่วคราว (เปลี่ยนทุกรอบ submit) ทำให้ job เก่าขึ้น "?" เพราะ NID หลุดไฟล์.
registry นี้สะสม NID ทุกตัวที่เคย submit แบบถาวร → job เก่า/ใหม่ resolve ได้หมด.

ไฟล์เก็บ NID ดิบ (PII) → ต้อง gitignore.
best-effort: เขียน fail จะไม่ทำให้ job creation พัง (job สำคัญกว่า display).
"""
import json
import threading
from pathlib import Path

from app.utils.security import hash_nid

_ROOT = Path(__file__).resolve().parent.parent.parent  # app/utils/ → app/ → project root
_REGISTRY = _ROOT / "nid_registry.json"
_lock = threading.Lock()


def record_nid(nid: str) -> None:
    """บันทึก {hash: nid} ลง registry — idempotent, best-effort (ไม่ throw)"""
    if not nid:
        return
    try:
        h = hash_nid(nid)
        with _lock:
            data = {}
            if _REGISTRY.exists():
                try:
                    data = json.loads(_REGISTRY.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            if data.get(h) == nid:
                return  # มีแล้ว ไม่ต้องเขียนซ้ำ
            data[h] = nid
            tmp = _REGISTRY.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(_REGISTRY)  # atomic rename
    except Exception:
        pass  # best-effort — ห้าม break flow
