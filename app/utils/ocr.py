import re
import unicodedata
from datetime import datetime
from typing import Optional, Dict

import pytesseract
from PIL import Image, ImageFilter, ImageEnhance


def _preprocess(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    w, h = img.size
    if w < 800:
        img = img.resize((w * 2, h * 2), Image.LANCZOS)
    return img


def extract_slip(slip_path: str) -> Dict[str, Optional[str]]:
    """
    อ่านสลิปดึงข้อมูลครบ:
      - amount (float)        ยอดเงิน
      - reference (string)    เลขอ้างอิง (ใช้ป้องกันสลิปซ้ำ)
      - recipient (string)    เลขบัญชี/พร้อมเพย์ปลายทาง
      - raw_text              ข้อความ OCR ทั้งหมด (debug)
    """
    try:
        img = Image.open(slip_path)
        img = _preprocess(img)
        text = pytesseract.image_to_string(img, lang="tha+eng", config="--psm 6")
        # normalize: ํา (U+0E4D + U+0E32 decomposed) → ำ (U+0E33 sara-am)
        # NFC ไม่ช่วย เพราะ Thai combining chars ไม่ canonical-equivalent
        text = unicodedata.normalize("NFC", text)
        text = text.replace("ํา", "ำ")
    except Exception:
        return {"amount": None, "reference": None, "recipient": None, "raw_text": None}

    return {
        "amount": _parse_amount(text),
        "reference": _parse_reference(text),
        "recipient": _parse_recipient(text),
        "datetime": _parse_datetime(text),
        "bank": _parse_bank(text),
        "recipient_name": _parse_recipient_name(text),
        "raw_text": text,
    }


def _parse_amount(text: str) -> Optional[float]:
    """หายอดเงิน คืนเป็น float (เช่น 179.0)"""
    patterns = [
        r"(?:จำนวน|ยอด(?:เงิน)?|amount|ยอดโอน|จำนวนเงิน)[^\d]*(\d[\d,]*(?:\.\d{1,2})?)",
        r"(?:฿\s*|THB\s*)(\d[\d,]*(?:\.\d{1,2})?)",
        r"(\d[\d,]*\.\d{2})\s*(?:บาท|THB|฿)",
        r"(\d[\d,]+)\s*บาท",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue

    # fallback — หาตัวเลขดูเหมือนราคา
    for n in re.findall(r"\b(\d{2,5})(?:\.\d{2})?\b", text):
        val = int(n)
        if 50 <= val <= 99999:
            return float(val)
    return None


def _parse_reference(text: str) -> Optional[str]:
    """หาเลขอ้างอิงสลิป (ใช้ป้องกันการ submit สลิปซ้ำ)"""
    patterns = [
        # คีย์เวิร์ดชัดเจน (ทุกธนาคาร)
        r"(?:เลขที่อ้างอิง|รหัสอ้างอิง|เลขที่สลิป|เลขที่รายการ|หมายเลขรายการ"
        r"|transaction\s*(?:id|no|ref)|ref(?:erence)?\s*(?:no|id|code)?|slip\s*(?:id|no))"
        r"[\s:.#]*([A-Z0-9]{8,30})",
        # fallback — string ยาว alphanumeric ที่ไม่ใช่ชื่อ
        r"\b([A-Z0-9]{12,30})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


# รูปแบบบัญชีมาสก์ที่แสดง 4 ตัวท้าย — ใช้ร่วมกับ _account_match()
_MASKED_TAIL4 = re.compile(
    r"[Xx*\-\s]{2,}(\d{4})\b"          # XXXX4759 / x-4759 / ***-4759
    r"|(\d{4})-[Xx*]{2,}"              # 4759-XXX (บางธนาคารแสดงส่วนหน้า)
    r"|[Xx*]+(\d{4})[Xx*\-]*\b",       # XXXXX4759XXXX (มาสก์หลังด้วย)
    re.IGNORECASE,
)

# คีย์เวิร์ดที่นำหน้าบัญชีปลายทาง
_RECIPIENT_KEYWORDS = re.compile(
    r"(?:ผู้รับ|บัญชีผู้รับ|ปลายทาง|ไปยัง|โอนไปยัง|to|receiver|recipient"
    r"|acc(?:ount)?\.?\s*(?:no\.?|number)?|เลขที่บัญชี(?:ปลายทาง)?)",
    re.IGNORECASE,
)


def _parse_recipient(text: str) -> Optional[str]:
    """หา 4 ตัวท้ายของบัญชี/พร้อมเพย์ผู้รับ รองรับทุกธนาคารหลักไทย"""

    # 1. หาบริเวณหลัง keyword ผู้รับก่อน (แม่นที่สุด)
    kw_match = _RECIPIENT_KEYWORDS.search(text)
    if kw_match:
        window = text[kw_match.start(): kw_match.start() + 250]
        m = _MASKED_TAIL4.search(window)
        if m:
            tail = next(g for g in m.groups() if g)
            return tail.strip()

    # 2. Pattern เฉพาะรูปแบบมาตรฐานไทย (ไม่ต้องพึ่ง keyword)
    specific = [
        r"(\d-\d{4}-\d{5}-\d{2}-\d)",          # X-XXXX-XXXXX-XX-X (บัตร ปชช.)
        r"\d{3}-\d-\d{4}[Xx*]{1,2}-(\d{4})",   # 0XX-X-XXXX??-4759 (KBank style)
        r"\d{3}-\d-[Xx*]{4,5}-(\d{1,4})",      # XXX-X-XXXXX-4759
        r"[Xx*]{3,}(\d{4})\b",                  # XXXXX4759
        r"\b[Xx*]+[-\s]*(\d{4})\b",             # x-4759
    ]
    for pat in specific:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return None


# ── Date/Time ────────────────────────────────────────────────────────
_THAI_MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5,
    "มิถุนายน": 6, "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10,
    "พฤศจิกายน": 11, "ธันวาคม": 12,
}


def _parse_datetime(text: str) -> Optional[datetime]:
    """หา วันที่+เวลา จากสลิป (แปลง พ.ศ. → ค.ศ.)
    รองรับ: '18 พ.ค. 2569 - 08:34 น.', '17/02/67 10:30', '17 May 2024 14:23'"""
    # Pattern 1: Thai format — "วัน เดือน ปี - เวลา"
    m = re.search(
        r"(\d{1,2})\s+(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\."
        r"|มกราคม|กุมภาพันธ์|มีนาคม|เมษายน|พฤษภาคม|มิถุนายน|กรกฎาคม|สิงหาคม|กันยายน|ตุลาคม|พฤศจิกายน|ธันวาคม)"
        r"\s+(\d{2,4})[^\d]+(\d{1,2}):(\d{2})",
        text,
    )
    if m:
        day, month_th, year, hh, mm = m.groups()
        month = _THAI_MONTHS.get(month_th)
        year_int = int(year)
        if year_int < 100:
            year_int += 2500  # short BE year
        if year_int >= 2400:
            year_int -= 543  # BE → CE
        try:
            return datetime(year_int, month, int(day), int(hh), int(mm))
        except (ValueError, TypeError):
            pass

    # Pattern 2: DD/MM/YY or DD/MM/YYYY HH:MM
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+(\d{1,2}):(\d{2})", text)
    if m:
        day, month, year, hh, mm = m.groups()
        year_int = int(year)
        if year_int < 100:
            year_int += 2500
        if year_int >= 2400:
            year_int -= 543
        try:
            return datetime(year_int, int(month), int(day), int(hh), int(mm))
        except (ValueError, TypeError):
            pass

    # Pattern 3: fallback — หา "วันที่" + DD + YYYY + HH:MM (เดือนอาจเพี้ยน)
    # ใช้ตอน OCR อ่านชื่อเดือนไม่ออก เช่น "พ.ค." → "wa."
    m = re.search(
        r"(?:วันที่|date)\D{0,5}(\d{1,2})\D{1,20}(\d{4})\D{1,20}(\d{1,2}):(\d{2})",
        text, re.IGNORECASE,
    )
    if m:
        day, year, hh, mm = m.groups()
        year_int = int(year)
        if year_int >= 2400:
            year_int -= 543
        # เดือนหาไม่ได้ — ใช้เดือนปัจจุบัน (จะ false positive น้อยถ้าเช็คเวลาด้วย)
        from datetime import datetime as _dt
        month = _dt.now().month
        try:
            dt = datetime(year_int, month, int(day), int(hh), int(mm))
            # ถ้าวันที่อนาคต — ลองเดือนก่อนหน้า
            if dt > _dt.now():
                month_prev = month - 1 if month > 1 else 12
                year_prev = year_int if month > 1 else year_int - 1
                dt = datetime(year_prev, month_prev, int(day), int(hh), int(mm))
            return dt
        except (ValueError, TypeError):
            pass

    return None


# ── Bank ─────────────────────────────────────────────────────────────
def _parse_bank(text: str) -> Optional[str]:
    """ดึงชื่อธนาคารจากสลิป (ส่วนใหญ่อยู่ท้าย 'โดย ธ. XXX')"""
    patterns = [
        r"(?:โดย\s+)?ธ(?:นาคาร|\.)\s*([^\s\n]{3,40})",  # ธ. กสิกรไทย / ธนาคารกสิกรไทย
        r"\b(KBank|SCB|BBL|KTB|TTB|TMB|GSB|BAY|KKP)\b",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


# ── Recipient name ───────────────────────────────────────────────────
def _parse_recipient_name(text: str) -> Optional[str]:
    """ดึงชื่อผู้รับ — ปกติอยู่หลังคำว่า 'ไปยัง'"""
    m = re.search(
        r"(?:ไปยัง|ผู้รับ|to|receiver|recipient)[\s:]+"
        r"((?:นาย|นาง|น\.ส\.|นางสาว|mr\.?|ms\.?|mrs\.?)?\s*[฀-๿a-zA-Z\s]{3,60})",
        text,
        re.IGNORECASE,
    )
    if m:
        name = m.group(1).strip()
        # ตัด noise — คำท้ายที่ไม่ใช่ชื่อ
        name = re.sub(r"\s{2,}.*$", "", name)  # ตัดที่ space ยาว
        return name.strip()
    return None


# backward-compat
def extract_amount(slip_path: str) -> Optional[str]:
    amount = extract_slip(slip_path)["amount"]
    return str(int(amount)) if amount is not None else None
