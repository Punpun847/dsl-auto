"""LLM-based multiple-choice answerer.

Provider priority: DeepSeek (primary) → Claude (fallback)
ส่ง question text + options ทุกข้อในชุดเดียว — คืน list ของ index (0-based)
"""
import asyncio
import json
import logging
import re
from typing import Dict, List, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Endpoints
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
CLAUDE_URL   = "https://api.anthropic.com/v1/messages"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"


def _build_prompt(questions: List[Dict]) -> str:
    lines = [
        "คุณเป็นผู้ตอบแบบทดสอบ multiple choice ที่แม่นยำ",
        "หลักสูตรเกี่ยวกับการเงิน ลงทุน เศรษฐกิจ การบัญชี การตลาด หรือทักษะธุรกิจ",
        "อ่านแต่ละข้อและเลือกคำตอบที่ถูกต้องที่สุด",
        "",
    ]
    for i, q in enumerate(questions):
        lines.append(f"=== ข้อ {i+1} ===")
        lines.append(q.get("q_text") or "")
        for j, opt in enumerate(q.get("options") or []):
            lines.append(f"  [{j}] {opt.get('text') or ''}")
        lines.append("")
    lines.append(
        'ตอบเป็น JSON เพียงอย่างเดียว ในรูปแบบ {"answers": [0,2,1,...]} '
        'โดยตัวเลขในอาเรย์คือ index (เริ่มที่ 0) ของตัวเลือกที่ถูก เรียงตามข้อ'
    )
    return "\n".join(lines)


def _parse_answer_response(text: str, n_questions: int, q_options: List[List]) -> Optional[List[int]]:
    """Parse LLM text response → list of 0-based indices"""
    try:
        parsed = json.loads(text)
        answers = parsed.get("answers") or []
    except Exception:
        m = re.search(r'"answers"\s*:\s*\[([^\]]+)\]', text)
        if not m:
            logger.warning(f"LLM response parse fail: {text[:200]}")
            return None
        answers = [int(x.strip()) for x in m.group(1).split(",") if x.strip().isdigit()]

    if len(answers) != n_questions:
        logger.warning(f"LLM answer length mismatch: {len(answers)} vs {n_questions}")
        answers = answers[:n_questions] + [0] * max(0, n_questions - len(answers))

    # clamp to valid option index
    for i, opts in enumerate(q_options):
        n_opts = len(opts)
        if n_opts and not (0 <= answers[i] < n_opts):
            answers[i] = 0
    return answers


async def _call_deepseek(prompt: str) -> Optional[str]:
    """Call DeepSeek API — return raw text or None on failure"""
    RETRY_STATUS = {429, 500, 502, 503, 504}
    BACKOFFS = [2, 5, 10]
    headers = {
        "Authorization": f"Bearer {settings.deepseek_api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(len(BACKOFFS) + 1):
                try:
                    res = await client.post(DEEPSEEK_URL, headers=headers, json=body)
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.NetworkError) as e:
                    if attempt < len(BACKOFFS):
                        logger.warning(f"DeepSeek net err: {type(e).__name__} — retry ใน {BACKOFFS[attempt]}s")
                        await asyncio.sleep(BACKOFFS[attempt])
                        continue
                    raise
                if res.status_code == 200 or res.status_code not in RETRY_STATUS:
                    break
                if attempt < len(BACKOFFS):
                    logger.warning(f"DeepSeek status={res.status_code} — retry ใน {BACKOFFS[attempt]}s")
                    await asyncio.sleep(BACKOFFS[attempt])
        if res.status_code != 200:
            logger.warning(f"DeepSeek status={res.status_code} body={res.text[:300]}")
            return None
        data = res.json()
        choices = data.get("choices") or []
        if not choices:
            logger.warning(f"DeepSeek no choices: {str(data)[:300]}")
            return None
        return (choices[0].get("message") or {}).get("content") or None
    except Exception as e:
        logger.warning(f"DeepSeek call failed: {type(e).__name__}: {e}")
        return None


async def _call_claude(prompt: str) -> Optional[str]:
    """Call Claude API — return raw text or None on failure"""
    RETRY_STATUS = {429, 500, 502, 503, 504}
    BACKOFFS = [2, 5, 10]
    headers = {
        "x-api-key": settings.claude_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 256,
        "messages": [{"role": "user", "content": prompt}],
    }
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            for attempt in range(len(BACKOFFS) + 1):
                try:
                    res = await client.post(CLAUDE_URL, headers=headers, json=body)
                except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.NetworkError) as e:
                    if attempt < len(BACKOFFS):
                        logger.warning(f"Claude net err: {type(e).__name__} — retry ใน {BACKOFFS[attempt]}s")
                        await asyncio.sleep(BACKOFFS[attempt])
                        continue
                    raise
                if res.status_code == 200 or res.status_code not in RETRY_STATUS:
                    break
                if attempt < len(BACKOFFS):
                    logger.warning(f"Claude status={res.status_code} — retry ใน {BACKOFFS[attempt]}s")
                    await asyncio.sleep(BACKOFFS[attempt])
        if res.status_code != 200:
            logger.warning(f"Claude status={res.status_code} body={res.text[:300]}")
            return None
        data = res.json()
        content = data.get("content") or []
        if not content:
            logger.warning(f"Claude no content: {str(data)[:300]}")
            return None
        return content[0].get("text") or None
    except Exception as e:
        logger.warning(f"Claude call failed: {type(e).__name__}: {e}")
        return None


async def answer_quiz(
    questions: List[Dict],
    force_provider: Optional[str] = None,
) -> Optional[List[int]]:
    """รับ list ของ {q_text, options: [{value, text}]} → คืน list of 0-based indices

    Provider priority (default = force_provider=None):
      1. DeepSeek (ถ้า DEEPSEEK_API_KEY ตั้งอยู่)
      2. Claude (ถ้า CLAUDE_API_KEY ตั้งอยู่)
      3. None

    force_provider:
      "deepseek" → ใช้แค่ DeepSeek (ไม่ fallback Claude)
      "claude"   → ใช้แค่ Claude (ข้าม DeepSeek) — ใช้เป็น second opinion ตอน DeepSeek ตอบผิด
    """
    if not questions:
        return None

    prompt = _build_prompt(questions)
    q_options = [q.get("options") or [] for q in questions]
    use_deepseek = force_provider != "claude"
    use_claude   = force_provider != "deepseek"

    # 1. DeepSeek (primary)
    if use_deepseek and settings.deepseek_api_key:
        logger.info(f"LLM: DeepSeek ถาม {len(questions)} ข้อ…")
        text = await _call_deepseek(prompt)
        if text:
            result = _parse_answer_response(text, len(questions), q_options)
            if result is not None:
                return result
        logger.warning("DeepSeek ตอบไม่ได้ — ลอง Claude ต่อ")

    # 2. Claude (fallback หรือ force)
    if use_claude and settings.claude_api_key:
        logger.info(f"LLM: Claude ถาม {len(questions)} ข้อ…")
        text = await _call_claude(prompt)
        if text:
            result = _parse_answer_response(text, len(questions), q_options)
            if result is not None:
                return result

    logger.info("LLM: ไม่มี provider ใดตอบได้ — return None")
    return None
