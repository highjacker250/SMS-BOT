# services/browser_automation.py
import asyncio
from playwright.async_api import async_playwright
import logging

log = logging.getLogger("BrowserAuto")

async def login_paypal(number, otp):
    """
    Playwright se PayPal login karega aur cookies return karega.
    """
    async with async_playwright() as p:
        # Headless=False mat karna production me, Render pe headless hi chalega
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            # 1. Login page kholo
            await page.goto("https://www.paypal.com/in/signin")
            await page.wait_for_timeout(3000)
            
            # 2. Number daalo aur Next click karo
            await page.fill('input[type="email"]', number)
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(4000)
            
            # 3. OTP page aayega, OTP daalo
            # (Yahan selectors change ho sakte hain, check karte rehna)
            try:
                await page.fill('input[name="otp"]', otp)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(5000)
            except:
                log.error("OTP input not found. Wrong selectors or no OTP required.")
                await browser.close()
                return {"status": "failed", "reason": "OTP input failed"}

            # 4. Cookies save karo
            cookies = await context.cookies()
            cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            await browser.close()
            return {"status": "success", "cookies": cookies_str}
            
        except Exception as e:
            log.error(f"Playwright Error: {e}")
            await browser.close()
            return {"status": "failed", "reason": str(e)}
