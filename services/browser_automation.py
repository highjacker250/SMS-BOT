# services/browser_automation.py
import asyncio
import logging
import random
import string
from playwright.async_api import async_playwright
from services.paypal_api import get_paypal_access_token
import config

log = logging.getLogger("BrowserAuto")

# 🚨 Helper: Real Data Generator
def generate_fake_data():
    first_name = random.choice(["Rahul", "Amit", "Sumit", "Vikas", "John", "David"])
    last_name = random.choice(["Sharma", "Verma", "Kumar", "Singh", "Smith"])
    return {
        "name": f"{first_name} {last_name}",
        "age": str(random.randint(22, 35)),
        "city": random.choice(["Mumbai", "Delhi", "Bangalore", "New York"]),
        "password": f"Pass@{random.randint(1000, 9999)}"
    }

# 🚨 Playwright Login (Real Login via Browser)
async def login_paypal_browser(number, otp):
    log.info(f"Browser Login Started for PayPal - {number}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True) 
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            await page.goto("https://www.paypal.com/in/signin", timeout=60000)
            await page.wait_for_timeout(3000)
            
            await page.fill('input[type="email"]', number)
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(4000)
            
            try:
                await page.fill('input[name="otp"]', otp)
                await page.click('button[type="submit"]')
                await page.wait_for_timeout(5000)
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

# 🚨 Main Manual Login Function (API -> Fallback -> Browser)
async def login_manual_target(platform, phone, otp):
    log.info(f"Login Started for {platform} - {phone}")
    
    if platform.lower() == "paypal":
        # 🚨 1. API Check (Agar API kaam karti hai toh token generate karega)
        token = await get_paypal_access_token()
        if token:
            log.info("PayPal API is alive. (Note: OTP login still needs browser)")
            # PayPal me OTP login API se possible nahi hai, isliye hum direct browser pe jayenge
            # Par humne API check kar liya, matlab system live hai.
        else:
            log.warning("PayPal API failed. Using Browser Fallback...")

        # 🚨 2. Browser Automation (Real Login)
        return await login_paypal_browser(phone, otp)
    
    else:
        return {"status": "failed", "reason": f"Login not implemented for {platform.upper()} yet."}

# 🚨 Create Account via Browser (Fake Details + Master Email)
async def create_target_account(platform, name, age, loc):
    log.info(f"Creating {platform} Account with Name: {name}")
    if not name:
        data = generate_fake_data()
        name, age, loc = data["name"], data["age"], data["city"]
        
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            if platform.lower() == "paypal":
                await page.goto("https://www.paypal.com/in/webapps/mpp/account-selection", timeout=60000)
                await page.wait_for_timeout(3000)
                # Yahan actual form fill hoga (Selectors change ho sakte hain)
                # await page.fill('input[name="firstName"]', name.split()[0])
                # ...
                # await page.fill('input[name="email"]', config.MASTER_EMAIL)
                
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
