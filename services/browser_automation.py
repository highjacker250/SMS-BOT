import asyncio
import logging
import os
from playwright.async_api import async_playwright
from services.paypal_api import get_paypal_access_token
import config

log = logging.getLogger("BrowserAuto")

# 🚨 Naya Helper: Screenshot Save Karo
async def take_screenshot(page):
    try:
        await page.screenshot(path="live_browser.png")
        log.info("Live screenshot updated.")
    except Exception as e:
        log.error(f"Screenshot failed: {e}")

async def login_paypal_browser(number, otp):
    log.info(f"Browser Login Started for PayPal - {number}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await page.goto("https://www.paypal.com/in/signin", timeout=60000)
            await page.wait_for_timeout(3000)
            await take_screenshot(page) # 📸

            await page.fill('input[type="email"]', number)
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(4000)
            await take_screenshot(page) # 📸

            try:
                await page.fill('input[name="otp"]', otp)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(5000)
                await take_screenshot(page) # 📸
            except:
                log.error("OTP input not found.")
                await browser.close()
                return {"status": "failed", "reason": "OTP input failed"}

            cookies = await context.cookies()
            cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
            await browser.close()
            return {"status": "success", "cookies": cookies_str}
        except Exception as e:
            log.error(f"Playwright Error: {e}")
            await browser.close()
            return {"status": "failed", "reason": str(e)}

async def login_manual_target(platform, phone, otp):
    log.info(f"Login Started for {platform} - {phone}")
    if platform.lower() == "paypal":
        token = await get_paypal_access_token()
        if token:
            log.info("PayPal API is alive.")
        else:
            log.warning("PayPal API failed. Using Browser Fallback...")
        return await login_paypal_browser(phone, otp)
    else:
        return {"status": "failed", "reason": f"Login not implemented for {platform.upper()} yet."}

async def create_target_account(platform, name, age, loc):
    log.info(f"Creating {platform} Account with Name: {name}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            if platform.lower() == "paypal":
                await page.goto("https://www.paypal.com/in/webapps/mpp/account-selection", timeout=60000)
                await page.wait_for_timeout(3000)
                await take_screenshot(page) # 📸
                
                # (Form fill logic yahan aayega)
                
                cookies = await context.cookies()
                cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])
                await browser.close()
                return {"status": "success", "cookies": cookies_str, "phone": "+919999999999"}
            else:
                return {"status": "failed", "reason": "Platform creation not implemented."}
        except Exception as e:
            log.error(f"Playwright Create Error: {e}")
            await browser.close()
            return {"status": "failed", "reason": str(e)}
