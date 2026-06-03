"""Capture API ตอน user คลิก 'ขอรับวุฒิบัตร'"""
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient, SET_BASE


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

        captured = []
        OUT = Path('/tmp/cert_click_capture.json')
        def flush():
            OUT.write_text(json.dumps(captured, ensure_ascii=False, indent=2))

        async def on_req(r):
            if 'elearning.set.or.th' not in r.url or 'analytics' in r.url:
                return
            entry = {'method': r.method, 'url': r.url, 'body': r.post_data}
            captured.append(entry)
            flush()
            print(f'\n>>> {r.method} {r.url[:120]}')
            if r.post_data:
                print(f'    BODY: {r.post_data[:300]}')

        async def on_resp(r):
            if 'elearning.set.or.th' not in r.url or 'analytics' in r.url:
                return
            try:
                txt = (await r.text())[:500]
            except: txt = '<err>'
            print(f'<<< {r.status} {r.url[:80]}')
            print(f'    RESP: {txt}')
            for c in reversed(captured):
                if c['url'] == r.url and 'response' not in c:
                    c['response'] = txt
                    c['status'] = r.status
                    break
            flush()

        client.page.on('request', on_req)
        client.page.on('response', on_resp)
        client.page.on('dialog', lambda d: asyncio.create_task(d.accept()))

        print('\n' + '=' * 60)
        print('📝 กดปุ่ม "ขอรับวุฒิบัตร" (สีน้ำเงิน)')
        print('   จากนั้นรอ — ผมจะ capture API ทั้งหมด')
        print('=' * 60 + '\n')

        await client.page.wait_for_timeout(3 * 60 * 1000)


if __name__ == '__main__':
    asyncio.run(main())
