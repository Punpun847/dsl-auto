import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.worker.dsl_client import DSLClient


async def main():
    async with DSLClient(headless=False) as client:
        await client.login('1100201764358', 'Poonnapob200432')
        await client.goto_set()
        eid = 24395061
        for path in ['/exam/pre-test', '/exam/post-test', '/exam/exam']:
            url = f'https://elearning.set.or.th/SETStudentLoan/enroll/{eid}{path}'
            print(f'--- {path}')
            await client.page.goto(url, wait_until='domcontentloaded', timeout=30000)
            await client.page.wait_for_timeout(8000)
            r = await client.page.evaluate("""() => {
                const radios = document.querySelectorAll('input[type="radio"]').length;
                const loading = document.body.innerText.includes('Loading');
                const headers = Array.from(document.querySelectorAll('h1, h2, h3, .h1, .h2, .h3'))
                    .map(h => (h.innerText||'').trim()).filter(t => t).slice(0, 5);
                const sampleText = document.body.innerText.replace(/\s+/g, ' ').slice(0, 300);
                return {radios, loading, headers, sampleText};
            }""")
            print(f'  radios: {r["radios"]}  loading: {r["loading"]}')
            print(f'  headers: {r["headers"]}')
            print(f'  body: {r["sampleText"]}')
            print()


if __name__ == '__main__':
    asyncio.run(main())
