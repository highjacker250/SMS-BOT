"""
Obscura Browser Integration Manager.

This module manages the Obscura browser (anti-detection Chromium) integration.
It works with the new BrowserManager to provide seamless CDP connection fallback.
"""
import asyncio
import logging
import os
import shutil
import subprocess
import time
from playwright.async_api import async_playwright

# Use lazy import to avoid circular dependency
# from services.browser import BrowserManager, get_browser_manager

log = logging.getLogger("Obscura")

_OBSCURA_PROC = None
_OBSCURA_PORT = 9222
_OBSCURA_READY = False


def _is_obscura_installed() -> bool:
    """Check if obscura binary exists."""
    return shutil.which("obscura") is not None


async def start_obscura():
    """
    Start obscura headless server on port 9222. If missing, log and return False.
    This is called by BrowserManager during initialization.
    """
    global _OBSCURA_PROC, _OBSCURA_READY

    if _OBSCURA_READY:
        return True

    if not _is_obscura_installed():
        log.warning("Obscura binary not found. Falling back to default Chromium.")
        return False

    try:
        log.info(f"Starting Obscura CDP on port {_OBSCURA_PORT}...")
        _OBSCURA_PROC = subprocess.Popen(
            ["obscura", "serve", "--port", str(_OBSCURA_PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for port to open
        for _ in range(10):
            if _OBSCURA_PROC.poll() is not None:
                log.error("Obscura process died immediately.")
                _OBSCURA_PROC = None
                return False
            try:
                import socket
                s = socket.socket()
                s.settimeout(1)
                s.connect(("127.0.0.1", _OBSCURA_PORT))
                s.close()
                _OBSCURA_READY = True
                log.info(f"✅ Obscura CDP ready on 127.0.0.1:{_OBSCURA_PORT}")
                return True
            except Exception:
                await asyncio.sleep(1)
        log.error("Obscura failed to open port.")
        return False
    except Exception as e:
        log.error(f"Obscura start error: {e}")
        return False


def stop_obscura():
    """Stop the Obscura process."""
    global _OBSCURA_PROC, _OBSCURA_READY
    if _OBSCURA_PROC:
        _OBSCURA_PROC.terminate()
        _OBSCURA_PROC = None
    _OBSCURA_READY = False


async def get_obscura_cdp_url() -> str | None:
    """
    Get the Obscura CDP URL if available.
    Returns None if Obscura is not available.
    """
    if not _is_obscura_installed():
        return None

    # Try to start Obscura
    success = await start_obscura()
    if success and _OBSCURA_READY:
        return f"http://127.0.0.1:{_OBSCURA_PORT}"
    return None


async def create_browser_with_obscura(headless: bool = True):
    """
    Create a BrowserManager instance that will attempt to use Obscura CDP.
    This is a factory function that integrates with the new BrowserManager.
    Uses lazy import to avoid circular dependency.
    """
    from services.browser import BrowserManager
    mgr = BrowserManager()
    # The BrowserManager will internally call start_obscura() during start()
    await mgr.start()
    return mgr


# Backward compatibility function
async def get_browser_context(playwright: async_playwright):
    """
    Legacy function for backward compatibility.
    Returns browser, context, used_obscura flag.
    """
    global _OBSCURA_READY

    cdp_url = await get_obscura_cdp_url()

    if cdp_url:
        try:
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            context = browser.contexts[0] if browser.contexts else await browser.new_context()
            log.info("Connected to Obscura via CDP.")
            return browser, context, True
        except Exception as e:
            log.warning(f"Obscura CDP connect failed ({e}). Falling back.")
            _OBSCURA_READY = False

    browser = await playwright.chromium.launch(headless=True)
    context = await browser.new_context()
    log.info("Using default Chromium (headless).")
    return browser, context, False