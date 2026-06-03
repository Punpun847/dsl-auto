"""Probe API endpoints ที่อาจคืน quiz questions + answers"""
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
        post_quiz_id = 2355  # known from earlier

        # 1. สร้าง attempt ใหม่
        e2q = await client.page.evaluate(
            f"""async () => {{
                const r = await fetch('/api/site/enroll2quiz', {{
                    method:'POST', credentials:'include',
                    headers: {{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8','X-Requested-With':'XMLHttpRequest'}},
                    body: 'eid={eid}&qid={post_quiz_id}&type=3'
                }});
                return await r.json();
            }}"""
        )
        e2q_id = e2q.get('enroll2quiz')
        print(f'enroll2quiz_id = {e2q_id}')

        # 2. ลอง endpoints ต่างๆ
        endpoints = [
            f'/api/site/enroll2quiz/{e2q_id}',
            f'/api/site/enroll2quiz/{e2q_id}/questions',
            f'/api/site/quiz/{post_quiz_id}',
            f'/api/site/quiz/{post_quiz_id}/questions',
            f'/api/site/enroll/{eid}/quiz/{post_quiz_id}',
            f'/api/site/quizs/{post_quiz_id}',
            f'/api/site/quizs/{post_quiz_id}/questions',
            f'/api/site/exam/{e2q_id}',
            f'/api/site/exam/{e2q_id}/questions',
            f'/api/site/questions?quiz_id={post_quiz_id}',
            f'/api/site/questions?enroll2quiz={e2q_id}',
        ]
        for ep in endpoints:
            try:
                r = await client.page.evaluate(
                    f"""async () => {{
                        const r = await fetch('{ep}', {{credentials:'include'}});
                        const t = await r.text();
                        return {{status: r.status, body: t.slice(0, 600)}};
                    }}"""
                )
                marker = '✅' if r['status'] == 200 and 'html' not in r['body'][:50].lower() else '❌'
                print(f'{marker} {r["status"]} {ep}')
                if r['status'] == 200 and 'html' not in r['body'][:50].lower():
                    print(f'   body: {r["body"]}')
            except Exception as e:
                print(f'⚠️  ERR {ep}: {e}')


if __name__ == '__main__':
    asyncio.run(main())
