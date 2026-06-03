"""Inject Claude-answered คำตอบเข้า Redis answer_cache โดยตรง

คำตอบที่ผมวิเคราะห์ — course 666 (รู้ทันภัยทางการเงิน) จาก pending_dump 27 ข้อ
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "stubs"))

import redis
from app.utils.pending_dump import read_pending


def text_hash(t: str) -> str:
    return hashlib.sha1(" ".join((t or "").split()).encode()).hexdigest()[:8]


# คำตอบที่ผม (Claude) วิเคราะห์ — { q_hash: option_value }
ANSWERS = {
    # แอปกู้ผิดกฎหมาย (Q1, Q6) — ข้อที่อนุมัติเต็ม + ดอกเบี้ยตามทางการ = ถูกกฎหมาย
    "a2e70daa9bf5": "41101",
    "db284c0559d0": "41101",
    # Call Center รูปแบบหลอก (Q2, Q4) — I + II (โทรอ้างหน่วยงาน + ให้ตื่นเต้น)
    "013e3eb558a2": "41095",
    "ef0ae4ba0428": "41095",
    # ไม่ใช่วิธีป้องกัน (Q3, Q5, Q7) — ตั้ง Password เกี่ยวกับข้อมูลตัวเอง + จำอัตโนมัติ
    "ba0ae32e5f41": "41104",
    "d6569a9da68c": "41104",
    "59f120e757ab": "41104",
    # Q8, Q14 — ปลอมเป็นตลาดหลักทรัพย์ชักชวนสัมมนา (เป็นแชร์ลูกโซ่ ไม่ใช่ออนไลน์)
    "29b7e4534c21": "41132",
    "2b2c7e82d854": "41132",
    # Q9, Q23, Q27 — Fill blank: ไม่มีนโยบายโทร / มีข้อมูลอยู่แล้ว / ธนาคาร
    "1d35902efae0": "41115",
    "ec86c30fbefd": "41115",
    "f4c903ebf9ff": "41115",
    # Q10, Q19, Q24 — แชร์ลูกโซ่: I + III (ผลตอบแทนการันตี = สูงผิดปกติ ไม่ใช่เหมาะสม)
    "f86264d9af80": "41108",
    "8f6e7c61ed63": "41108",
    "56f2d5d137f0": "41108",
    # Q11, Q15, Q20 — ลำดับเมื่อตกเป็นเหยื่อ: ธนาคาร > แจ้งความ > ธปท.
    "afd223d07631": "41122",
    "a03a7e53aec8": "41122",
    "e9256480ad58": "41122",
    # Q12, Q18, Q21 — สงสัยแชร์ลูกโซ่: ใช้ทั้ง 3 หน่วยงาน
    "9719e1cea137": "41114",
    "e0aaf33312d4": "41114",
    "a5bf3d2a5659": "41114",
    # Q13, Q17, Q26 — กลโกงโจรออนไลน์: ใช้ทั้ง 3 รูปแบบ
    "3837061de8f3": "41130",
    "5ff2c8235bb2": "41130",
    "716f1545a95b": "41130",
    # Q16, Q22, Q25 — Call Center อายัดบัญชี: II + III (ตั้งสติ + โทรกลับ Call Center ธนาคารเอง)
    "1035d7d4d006": "41125",
    "bf8ac36ad72d": "41125",
    "816627fe1e94": "41125",
}


def main():
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    pending = read_pending()

    # map q_hash → q_text + options (เพื่อใส่ text_hash ลง cache value)
    by_hash = {q["q_hash"]: q for q in pending}

    saved = 0
    for qh, opt_value in ANSWERS.items():
        q = by_hash.get(qh)
        if not q:
            print(f"  ⚠️  {qh}: ไม่เจอใน pending_dump (อาจถูก promote ไปแล้ว)")
            continue
        # หา option text จาก value
        chosen_text = None
        for o in q.get("options", []):
            if str(o.get("value")) == str(opt_value):
                chosen_text = o.get("text", "")
                break
        if chosen_text is None:
            print(f"  ❌ {qh}: ไม่เจอ option value={opt_value}")
            continue
        # cache value = {"v": "...", "t": "<text_hash>"}
        cache_val = json.dumps(
            {"v": str(opt_value), "t": text_hash(chosen_text)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        r.hset("dsl:answer_cache", qh, cache_val)
        saved += 1
        print(f"  ✅ {qh} → value={opt_value} ({chosen_text[:50]})")

    total = r.hlen("dsl:answer_cache")
    print(f"\n💾 บันทึก {saved} ข้อ → Redis answer_cache (รวม {total} ข้อ)")


if __name__ == "__main__":
    main()
