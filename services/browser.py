"""
Browser automation service with guaranteed resource cleanup.
"""
import asyncio
import logging
import base64
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Optional, AsyncGenerator
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from services.obscura_manager import start_obscura, get_browser_context
import constants as C

log = logging.getLogger("Browser")


@dataclass
class BrowserConfig:
    """Browser automation configuration."""
    navigation_timeout: int = C.Timeouts.PLAYWRIGHT_NAVIGATION * 1000
    element_timeout: int = C.Timeouts.PLAYWRIGHT_ELEMENT * 1000
    max_contexts: int = C.Limits.MAX_BROWSER_CONTEXTS
    headless: bool = True


class BrowserManager:
    """
    Manages Playwright browser lifecycle with guaranteed cleanup.
    Uses context managers to ensure browsers are always closed.
    """

    def __init__(self, cfg: Optional[BrowserConfig] = None):
        self.cfg = cfg or BrowserConfig()
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._contexts: list[BrowserContext] = []
        self._obscura_started = False

    async def start(self) -> None:
        """Initialize Playwright and browser."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.cfg.headless,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                ]
            )
            log.info("Browser started")

    async def stop(self) -> None:
        """Stop Playwright and close all resources."""
        for ctx in self._contexts:
            try:
                await ctx.close()
            except Exception as e:
                log.warning(f"Error closing context: {e}")
        self._contexts.clear()

        if self._browser:
            try:
                await self._browser.close()
            except Exception as e:
                log.warning(f"Error closing browser: {e}")
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception as e:
                log.warning(f"Error stopping playwright: {e}")
            self._playwright = None

        self._obscura_started = False
        log.info("Browser stopped")

    @asynccontextmanager
    async def context(self, **kwargs) -> AsyncGenerator[BrowserContext, None]:
        """Create a new browser context with automatic cleanup."""
        if not self._browser:
            await self.start()

        if len(self._contexts) >= self.cfg.max_contexts:
            # Close oldest context
            old = self._contexts.pop(0)
            try:
                await old.close()
            except Exception:
                pass

        ctx = await self._browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent=(
                'Mozilla/5.0 (Linux; Android 10; SM-G973F) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Mobile Safari/537.36'
            ),
            **kwargs
        )
        self._contexts.append(ctx)
        try:
            yield ctx
        finally:
            if ctx in self._contexts:
                self._contexts.remove(ctx)
            try:
                await ctx.close()
            except Exception as e:
                log.warning(f"Error closing context: {e}")

    @asynccontextmanager
    async def page(self, **kwargs) -> AsyncGenerator[Page, None]:
        """Create a new page with automatic cleanup."""
        async with self.context(**kwargs) as ctx:
            page = await ctx.new_page()
            try:
                yield page
            finally:
                try:
                    await page.close()
                except Exception:
                    pass


class LoginAutomation:
    """
    Platform-specific login automation using Playwright.
    """

    def __init__(self, browser_mgr: BrowserManager):
        self.browser = browser_mgr

    async def take_screenshot(self, page: Page, path: str = "live_browser.png") -> bool:
        """Take screenshot for live view."""
        try:
            await page.screenshot(path=path, full_page=True)
            return True
        except Exception as e:
            log.error(f"Screenshot failed: {e}")
            return False

    async def login_with_url(
        self,
        url: str,
        phone: str,
        password: Optional[str] = None,
        otp: Optional[str] = None
    ) -> dict:
        """
        Automate login for a detected platform.
        Returns dict with status, cookies, and metadata.
        """
        platform = self._detect_platform(url)
        if platform == "Unknown":
            return {
                "status": "failed",
                "reason": f"Platform not detected from URL: {url}",
                "platform": platform
            }

        target_url = C.PLATFORM_LOGIN_URLS.get(platform, url)
        log.info(f"Logging into {platform} at {target_url}")

        try:
            async with self.browser.page() as page:
                # Navigate to login page
                await page.goto(target_url, timeout=self.cfg.navigation_timeout, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)
                await self.take_screenshot(page)

                # Platform-specific automation
                success = await self._automate_login(page, platform, phone, password, otp)
                await self.take_screenshot(page)

                if not success:
                    return {"status": "failed", "reason": "Login automation failed", "platform": platform}

                # Extract cookies
                cookies = await page.context.cookies()
                cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                return {
                    "status": "success",
                    "cookies": cookies_str,
                    "platform": platform,
                    "final_url": page.url,
                    "reason": "Login page reached, cookies saved."
                }

        except Exception as e:
            log.error(f"Playwright error in login_with_url: {e}")
            return {"status": "failed", "reason": str(e), "platform": platform}

    def _detect_platform(self, url: str) -> str:
        """Detect platform from URL."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url if "://" in url else f"https://{url}")
            domain_parts = (parsed.netloc or "").lower().split(".")
            for part in domain_parts:
                if part in C.PLATFORM_DOMAIN_MAP:
                    return C.PLATFORM_DOMAIN_MAP[part]
        except Exception:
            pass
        return "Unknown"

    async def _automate_login(
        self,
        page: Page,
        platform: str,
        phone: str,
        password: Optional[str],
        otp: Optional[str]
    ) -> bool:
        """Platform-specific login automation."""
        try:
            if platform == "PayPal":
                return await self._login_paypal(page, phone, otp)
            elif platform == "Facebook":
                return await self._login_facebook(page, phone, password)
            elif platform == "Instagram":
                return await self._login_instagram(page, phone, password)
            elif platform == "Google":
                return await self._login_google(page, phone, password)
            elif platform == "GitHub":
                return await self._login_github(page, phone, password)
            elif platform == "Twitter":
                return await self._login_twitter(page, phone, password)
            elif platform == "Telegram":
                return await self._login_telegram(page, phone)
            else:
                log.warning(f"No automation for platform: {platform}")
                return True  # Just reach the page
        except Exception as e:
            log.warning(f"{platform} form fill failed: {e}")
            return False

    async def _login_paypal(self, page: Page, phone: str, otp: Optional[str]) -> bool:
        await page.fill('input[type="email"]', phone, timeout=self.cfg.element_timeout)
        await page.click('button[type="submit"]', timeout=self.cfg.element_timeout)
        await page.wait_for_timeout(4000)
        if otp:
            await page.fill('input[name="otp"]', otp, timeout=self.cfg.element_timeout)
            await page.click('button[type="submit"]', timeout=self.cfg.element_timeout)
            await page.wait_for_timeout(5000)
        return True

    async def _login_facebook(self, page: Page, phone: str, password: Optional[str]) -> bool:
        await page.fill('input[name="email"]', phone, timeout=self.cfg.element_timeout)
        if password:
            await page.fill('input[name="pass"]', password, timeout=self.cfg.element_timeout)
        await page.click('button[name="login"]', timeout=self.cfg.element_timeout)
        await page.wait_for_timeout(5000)
        return True

    async def _login_instagram(self, page: Page, phone: str, password: Optional[str]) -> bool:
        await page.fill('input[name="username"]', phone, timeout=self.cfg.element_timeout)
        if password:
            await page.fill('input[name="password"]', password, timeout=self.cfg.element_timeout)
        await page.click('button[type="submit"]', timeout=self.cfg.element_timeout)
        await page.wait_for_timeout(5000)
        return True

    async def _login_google(self, page: Page, phone: str, password: Optional[str]) -> bool:
        await page.fill('input[type="email"]', phone, timeout=self.cfg.element_timeout)
        await page.click('button:has-text("Next")', timeout=self.cfg.element_timeout)
        await page.wait_for_timeout(3000)
        if password:
            await page.fill('input[type="password"]', password, timeout=self.cfg.element_timeout)
            await page.click('button:has-text("Next")', timeout=self.cfg.element_timeout)
            await page.wait_for_timeout(5000)
        return True

    async def _login_github(self, page: Page, phone: str, password: Optional[str]) -> bool:
        await page.fill('input[name="login"]', phone, timeout=self.cfg.element_timeout)
        if password:
            await page.fill('input[name="password"]', password, timeout=self.cfg.element_timeout)
        await page.click('input[name="commit"]', timeout=self.cfg.element_timeout)
        await page.wait_for_timeout(5000)
        return True

    async def _login_twitter(self, page: Page, phone: str, password: Optional[str]) -> bool:
        await page.fill('input[name="text"]', phone, timeout=self.cfg.element_timeout)
        await page.click('div[role="button"]:has-text("Next")', timeout=self.cfg.element_timeout)
        await page.wait_for_timeout(3000)
        if password:
            await page.fill('input[name="password"]', password, timeout=self.cfg.element_timeout)
            await page.click('div[role="button"]:has-text("Log in")', timeout=self.cfg.element_timeout)
            await page.wait_for_timeout(5000)
        return True

    async def _login_telegram(self, page: Page, phone: str) -> bool:
        # Telegram Web requires manual OTP entry
        await page.wait_for_timeout(2000)
        return True

    async def create_account(
        self,
        platform: str,
        name: str,
        age: str,
        location: str
    ) -> dict:
        """Create a new account (signup flow)."""
        signup_urls = {
            "paypal": "https://www.paypal.com/in/webapps/mpp/account-selection",
            "facebook": "https://www.facebook.com/r.php",
            "instagram": "https://www.instagram.com/accounts/emailsignup/",
            "google": "https://accounts.google.com/SignUp",
        }
        target_url = signup_urls.get(platform.lower())
        if not target_url:
            return {"status": "failed", "reason": "Platform creation not implemented"}

        try:
            async with self.browser.page() as page:
                await page.goto(target_url, timeout=self.cfg.navigation_timeout)
                await page.wait_for_timeout(4000)
                await self.take_screenshot(page)

                # Basic form fill (best effort)
                await self._fill_signup_form(page, platform, name, age, location)
                await self.take_screenshot(page)

                cookies = await page.context.cookies()
                cookies_str = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

                return {"status": "success", "cookies": cookies_str, "platform": platform}
        except Exception as e:
            log.error(f"Account creation failed: {e}")
            return {"status": "failed", "reason": str(e), "platform": platform}

    async def _fill_signup_form(self, page: Page, platform: str, name: str, age: str, location: str):
        """Best-effort signup form filling."""
        try:
            if platform.lower() == "facebook":
                parts = name.split()
                await page.fill('input[name="firstname"]', parts[0], timeout=5000)
                await page.fill('input[name="lastname"]', parts[-1] if len(parts) > 1 else "Kumar", timeout=5000)
                email = f"{name.lower().replace(' ', '')}@gmail.com"
                await page.fill('input[name="reg_email__"]', email, timeout=5000)
                await page.fill('input[name="reg_passwd__"]', "Password123!", timeout=5000)
        except Exception as e:
            log.warning(f"Signup form fill failed: {e}")


# Global browser manager
_browser_mgr: Optional[BrowserManager] = None
_login_automation: Optional[LoginAutomation] = None


async def get_browser_manager() -> BrowserManager:
    global _browser_mgr
    if _browser_mgr is None:
        _browser_mgr = BrowserManager()
        await _browser_mgr.start()
    return _browser_mgr


async def get_login_automation() -> LoginAutomation:
    global _login_automation
    if _login_automation is None:
        mgr = await get_browser_manager()
        _login_automation = LoginAutomation(mgr)
    return _login_automation


async def close_browser() -> None:
    """Close browser on shutdown."""
    global _browser_mgr, _login_automation
    if _browser_mgr:
        await _browser_mgr.stop()
        _browser_mgr = None
    _login_automation = None


# Backward compatibility
async def login_with_url(url: str, phone: str, otp: str = None, password: str = None):
    """Deprecated: Use get_login_automation().login_with_url()"""
    import warnings
    warnings.warn("login_with_url() is deprecated, use get_login_automation().login_with_url()", DeprecationWarning, stacklevel=2)
    automation = await get_login_automation()
    return await automation.login_with_url(url, phone, password, otp)


async def login_paypal_browser(number: str, otp: str):
    """Deprecated wrapper."""
    import warnings
    warnings.warn("login_paypal_browser() is deprecated", DeprecationWarning, stacklevel=2)
    automation = await get_login_automation()
    return await automation.login_with_url("https://paypal.com", number, otp=otp)


async def create_target_account(platform: str, name: str, age: str, loc: str):
    """Deprecated wrapper."""
    import warnings
    warnings.warn("create_target_account() is deprecated", DeprecationWarning, stacklevel=2)
    automation = await get_login_automation()
    return await automation.create_account(platform, name, age, loc)