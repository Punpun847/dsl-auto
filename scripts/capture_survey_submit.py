"""Capture API call ตอน user คลิกส่งแบบสอบถามใน browser"""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient, SET_BASE


OUT = Path("/tmp/survey_capture.json")


async def main():
    nid, pwd, course_id = sys.argv[1], sys.argv[2], sys.argv[3]
    async with DSLClient(headless=False) as client:
        await client.login(nid, pwd)
        await client.goto_set()
        info = await client.page.evaluate(
            f'async () => (await fetch("/api/site/groups/SETStudentLoan/courses/{course_id}",{{credentials:"include"}})).json()'
        )
        eid = info.get('enroll_id')
        print(f'enroll_id={eid}')

        await client.page.goto(f'{SET_BASE}/enroll/{eid}/summary',
                                wait_until='domcontentloaded', timeout=30000)
        await client.page.wait_for_timeout(3000)

        # auto-expand survey accordion + scroll
        await client.page.evaluate("""() => {
            document.querySelectorAll('.collapse').forEach(c => {
                c.classList.add('show');
                c.style.display = 'block';
                c.style.height = 'auto';
                c.style.visibility = 'visible';
            });
            // scroll ไปที่ survey form
            const form = document.querySelector('#survey-form');
            if (form) form.scrollIntoView({behavior: 'smooth', block: 'center'});
        }""")
        await client.page.wait_for_timeout(1500)

        captured = []
        def _flush():
            OUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))

        async def on_req(r):
            if 'elearning.set.or.th' not in r.url:
                return
            if r.method == 'GET':
                return
            entry = {
                'method': r.method,
                'url': r.url,
                'body': r.post_data,
                'headers': {k: v for k, v in r.headers.items()
                            if k.lower() in ('content-type', 'x-requested-with', 'x-xsrf-token')},
            }
            captured.append(entry)
            _flush()
            print(f'\n>>> {r.method} {r.url}')
            print(f'    BODY: {(r.post_data or "")[:300]}')

        async def on_resp(r):
            if 'elearning.set.or.th' not in r.url:
                return
            if r.request.method == 'GET':
                return
            try:
                txt = await r.text()
                short = txt[:400]
            except Exception:
                short = '<err>'
            print(f'<<< {r.status} {r.url}')
            print(f'    RESP: {short}')
            for c in reversed(captured):
                if c['url'] == r.url and 'response_status' not in c:
                    c['response_status'] = r.status
                    c['response_body'] = txt[:1000] if isinstance(txt, str) else str(txt)[:1000]
                    break
            _flush()

        client.page.on('request', on_req)
        client.page.on('response', on_resp)

        print('\n' + '=' * 60)
        print('📝 ขั้นตอน:')
        print('   1. ในหน้า summary ที่เปิดอยู่ → scroll หา section "แบบสอบถาม"')
        print('   2. กด expand accordion → ตอบคำถามทุกข้อ')
        print('   3. กดปุ่ม "ส่งแบบสอบถาม"')
        print('   4. รอ 30 วินาที — script เก็บทุก API call')
        print('=' * 60 + '\n')

        await client.page.wait_for_timeout(5 * 60 * 1000)


if __name__ == '__main__':
    asyncio.run(main())
