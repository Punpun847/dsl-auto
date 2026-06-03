"""Smoke test ของ UI หลังเพิ่ม soft-enforce login"""
import os
from playwright.sync_api import sync_playwright

out = os.path.abspath("./screenshots")
os.makedirs(out, exist_ok=True)

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()

    # 1. logged-out — form with banner + greyed wizard
    page.goto("http://127.0.0.1:8000/", wait_until="networkidle", timeout=20000)
    page.evaluate("document.getElementById('form')?.scrollIntoView({behavior:'instant', block:'start'})")
    page.wait_for_timeout(800)
    page.screenshot(path=f"{out}/06_form_logged_out.png", full_page=False)
    print("1/3 logged-out form snapshot")

    # 2. click login button in banner → modal opens
    page.get_by_role("button", name="เข้าสู่ระบบ / สมัครสมาชิก").click()
    page.wait_for_timeout(600)
    page.screenshot(path=f"{out}/07_login_modal.png")
    print("2/3 login modal snapshot")

    # 3. register a fresh demo account → auto-login → reload form view
    # ใช้ scoped selector ภายใน modal (relative-positioned div ใน fixed overlay)
    modal = page.locator("div.fixed.inset-0.z-50")
    modal.locator('div.flex.bg-paper-1 button:has-text("สมัครสมาชิก")').click()
    page.wait_for_timeout(400)
    modal.locator('input[type=email]').fill("demo-ui3@test.com")
    modal.locator('input[type=password]').nth(0).fill("password123")
    modal.locator('input[type=password]').nth(1).fill("password123")
    modal.locator('form button[type=submit]').click()
    page.wait_for_timeout(4000)
    page.evaluate("document.getElementById('form')?.scrollIntoView({behavior:'instant', block:'start'})")
    page.wait_for_timeout(500)
    page.screenshot(path=f"{out}/08_form_logged_in.png", full_page=False)
    print("3/3 logged-in form snapshot")

    b.close()
