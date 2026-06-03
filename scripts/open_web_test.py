"""เปิดเว็บ + screenshot หน้าหลัก + คลิกผ่านขั้นตอน + check status"""
import os
from playwright.sync_api import sync_playwright

out = os.path.abspath("./screenshots")
os.makedirs(out, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, locale="th-TH")
    page = ctx.new_page()

    print("🌐 เปิด http://127.0.0.1:8000")
    page.goto("http://127.0.0.1:8000", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{out}/web_01_home.png", full_page=False)
    print("✅ home page screenshot")

    # scroll to form section
    page.evaluate("document.getElementById('form')?.scrollIntoView({behavior:'instant', block:'start'})")
    page.wait_for_timeout(1000)
    page.screenshot(path=f"{out}/web_02_form.png", full_page=False)
    print("✅ form section screenshot")

    # scroll to footer
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(800)
    page.screenshot(path=f"{out}/web_03_footer.png", full_page=False)
    print("✅ footer screenshot")

    # back to top
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(500)

    # try to click "เข้าสู่ระบบ"
    print()
    print("🖱  คลิก 'เข้าสู่ระบบ'...")
    try:
        page.locator("text=เข้าสู่ระบบ").first.click(timeout=5000)
        page.wait_for_timeout(1500)
        page.screenshot(path=f"{out}/web_04_login_modal.png")
        print("✅ login modal screenshot")
    except Exception as e:
        print(f"⚠️  click fail: {e}")

    # Try register fresh demo account
    print()
    print("📝 Register demo account...")
    try:
        modal = page.locator("div.fixed.inset-0.z-50")
        modal.locator('div.flex.bg-paper-1 button:has-text("สมัครสมาชิก")').click()
        page.wait_for_timeout(500)
        import time
        email = f"demo-{int(time.time())}@test.com"
        modal.locator('input[type=email]').fill(email)
        modal.locator('input[type=password]').nth(0).fill("password123")
        modal.locator('input[type=password]').nth(1).fill("password123")
        modal.locator('form button[type=submit]').click()
        page.wait_for_timeout(3000)
        print(f"✅ registered: {email}")

        # scroll to form (now should be unblocked)
        page.evaluate("document.getElementById('form')?.scrollIntoView({behavior:'instant', block:'start'})")
        page.wait_for_timeout(800)
        page.screenshot(path=f"{out}/web_05_after_login.png", full_page=False)
        print("✅ after-login screenshot")
    except Exception as e:
        print(f"⚠️  register fail: {e}")

    # Test /docs page
    print()
    print("🔧 เปิด /docs Swagger...")
    page.goto("http://127.0.0.1:8000/docs", wait_until="networkidle", timeout=15000)
    page.wait_for_timeout(1500)
    page.screenshot(path=f"{out}/web_06_swagger.png", full_page=False)
    print("✅ Swagger screenshot")

    # Test /admin-panel
    print()
    print("🛠  เปิด /admin-panel...")
    ctx2 = b.new_context(viewport={"width": 1280, "height": 900},
                         http_credentials={"username": "admin", "password": "admin1234"})
    page2 = ctx2.new_page()
    page2.goto("http://127.0.0.1:8000/admin-panel", wait_until="networkidle", timeout=15000)
    page2.wait_for_timeout(1500)
    page2.screenshot(path=f"{out}/web_07_admin.png", full_page=False)
    print("✅ admin-panel screenshot")

    b.close()
    print()
    print(f"📁 ทั้งหมดอยู่ที่: {out}/web_*.png")
