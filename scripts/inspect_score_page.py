"""ดูหน้า /exam/{exam_id}/score ว่าแสดงเฉลย/correct answer หรือไม่"""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()
        info = await client.page.evaluate(
            f'async () => (await fetch("/api/site/groups/SETStudentLoan/courses/{course_id}",{{credentials:"include"}})).json()'
        )
        eid = info.get('enroll_id')

        # ดึง history ของ post-test (quiz_id=2355 สำหรับ 1286)
        cert = await client.page.evaluate(
            f'async () => (await fetch("/api/site/enroll/{eid}/certificate",{{method:"POST", credentials:"include"}})).json()'
        )
        post_quiz_id = cert.get('exam', {}).get('quiz_id')
        post_exam_id = cert.get('exam', {}).get('id')
        print(f'post quiz_id={post_quiz_id} exam_id={post_exam_id}')

        # GET history เพื่อดู attempt IDs
        hist = await client.page.evaluate(
            f'async () => (await fetch("/api/site/exam/{post_quiz_id}/history?page=1&per_page=10&enroll_id={eid}",{{credentials:"include"}})).json()'
        )
        attempts = hist.get('data', [])
        print(f'attempts: {len(attempts)}')
        for a in attempts[:3]:
            print(f'  {a}')

        if not attempts:
            return

        # เปิดหน้า score ของ attempt ล่าสุด
        latest_exam_id = attempts[0]['id']
        score_url = f'https://elearning.set.or.th/SETStudentLoan/enroll/{eid}/exam/{latest_exam_id}/score'
        print(f'\nGOTO: {score_url}')
        await client.page.goto(score_url, wait_until='domcontentloaded', timeout=30000)
        await client.page.wait_for_timeout(8000)

        result = await client.page.evaluate("""() => {
            const out = {};
            out.url = location.href;
            // หา indicators ของ correct answer (label "ถูก", icon check, color green)
            const indicators = [];
            document.querySelectorAll('.correct, .right, .text-success, .badge-success, [data-correct], i.bi-check-circle, i.fa-check').forEach(el => {
                indicators.push({tag: el.tagName, cls: el.className.slice(0,80), text: (el.innerText||'').trim().slice(0,40)});
            });
            out.correctIndicators = indicators.slice(0, 10);
            out.indicatorCount = indicators.length;
            // ดู radio + checked state
            const radios = [];
            document.querySelectorAll('input[type="radio"]').forEach(r => {
                radios.push({name: r.name, value: r.value, checked: r.checked, disabled: r.disabled, cls: (r.className||'').slice(0,40)});
            });
            out.radios = radios;
            out.radioCount = radios.length;
            // หาคำว่า "เฉลย", "คำตอบที่ถูก", "Correct Answer"
            const bodyText = document.body.innerText;
            const keywords = ['เฉลย', 'คำตอบที่ถูก', 'Correct Answer', 'Answer Key', 'ตอบถูก', 'ตอบผิด', 'คำตอบ'];
            out.keywordFound = keywords.filter(k => bodyText.includes(k));
            out.bodyPreview = bodyText.slice(0, 800);
            return out;
        }""")
        import json
        print('\n=== SCORE PAGE ===')
        print(f'URL: {result["url"]}')
        print(f'radios: {result["radioCount"]}, correct indicators: {result["indicatorCount"]}')
        print(f'keywords found: {result["keywordFound"]}')
        if result.get('radios'):
            print('first radios:')
            for r in result['radios'][:10]:
                print(f'  {r}')
        if result.get('correctIndicators'):
            print('correct indicators:')
            for i in result['correctIndicators']:
                print(f'  {i}')
        print('\nBODY PREVIEW:')
        print(result['bodyPreview'])
        await client.page.wait_for_timeout(30000)


if __name__ == '__main__':
    asyncio.run(main())
