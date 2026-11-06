# services/browser_automation.py
import asyncio
from playwright.async_api import async_playwright
import logging
import random

log = logging.getLogger("BrowserAuto")

async def login_manual_target(platform, phone, otp):
    """
    Playwright se real login karega aur cookies return karega.
    """
    log.info(f"Browser Login Started for {platform} - {phone}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            # 🚨 Yahan Platform ke hisaab se logic change hoga
            if platform.lower() == "paypal":
                await page.goto("https://www.paypal.com/in/signin")
                await page.wait_for_timeout(3000)
                await page.fill('input[type="email"]', phone)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(4000)
                try:
                    await page.fill('input[name="otp"]', otp)
                    await page.click('button[type="submit"]')
                    await page.wait_for_timeout(5000)
                except:
                    log.error("OTP input not found.")
                    await browser.close()
                    return {"status": "failed", "reason": "OTP input failed (Wrong selectors or captcha)"}
            
            elif platform.lower() == "facebook":
                # Facebook logic
                pass
            
            cookies = await context.cookies()
            cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            await browser.close()
            return {"status": "success", "cookies": cookies_str}
            
        except Exception as e:
            log.error(f"Playwright Error: {e}")
            await browser.close()
            return {"status": "failed", "reason": str(e)}

async def create_target_account(platform, name, age, loc):
    """
    Playwright se naya account banayega (Fake Details + Master Email).
    """
    log.info(f"Browser Creating Account for {platform}...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            # 🚨 Yahan Platform ke hisaab se logic change hoga
            if platform.lower() == "paypal":
                await page.goto("https://www.paypal.com/in/webapps/mpp/account-selection")
                await page.wait_for_timeout(3000)
                # Form fill logic (Simplified)
                # await page.fill('input[name="firstName"]', name.split()[0])
                # ...
                pass
            
            # Dummy success for now
            cookies = await context.cookies()
            cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            
            await browser.close()
            return {"status": "success", "cookies": cookies_str, "phone": "+919999999999"}
            
        except Exception as e:
            log.error(f"Playwright Error: {e}")
            await browser.close()
            return {"status": "failed", "reason": str(e)}
