import asyncio
import logging
import subprocess
import time
import aiohttp
import os

log = logging.getLogger("WARP")
_WARP_PROCESS = None

async def start_warp():
    global _WARP_PROCESS
    if _WARP_PROCESS is not None:
        return True # Already running
        
    log.info("Starting Cloudflare WARP (warp-plus)...")
    
    try:
        # warp-plus SOCKS5 proxy bind karega port 40000 pe
        cmd = ["warp-plus", "-b", "127.0.0.1:40000", "-4"]
        
        _WARP_PROCESS = subprocess.Popen(
            cmd, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        log.info("WARP process started. Waiting for it to be ready...")
        
        # Wait for proxy to be ready
        for _ in range(15):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get("https://api.ipify.org?format=json", proxy="socks5://127.0.0.1:40000", timeout=3) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            log.info(f"✅ WARP Proxy is LIVE! IP: {data.get('ip')}")
                            return True
            except Exception:
                pass
            await asyncio.sleep(2)
        
        log.error("WARP proxy failed to start within timeout.")
        _WARP_PROCESS = None
        return False
    except FileNotFoundError:
        log.error("warp-plus executable not found. Check build command.")
        return False
    except Exception as e:
        log.error(f"WARP startup error: {e}")
        return False

def stop_warp():
    global _WARP_PROCESS
    if _WARP_PROCESS:
        _WARP_PROCESS.terminate()
        _WARP_PROCESS = None
        log.info("WARP process stopped.")

def get_warp_proxy():
    """Returns the WARP proxy dict for Pyrogram"""
    return {
        "scheme": "socks5",
        "hostname": "127.0.0.1",
        "port": 40000
    }
