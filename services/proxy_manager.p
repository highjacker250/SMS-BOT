import aiohttp
import random
import logging
import asyncio
import database as db

log = logging.getLogger("ProxyManager")

async def fetch_free_proxies():
    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt"
    ]
    proxies = []
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        lines = text.strip().split('\n')[:30] # Get top 30
                        for line in lines:
                            if ":" in line: proxies.append(line.strip())
            except Exception as e:
                log.error(f"Proxy fetch error: {e}")
    return proxies

async def check_proxy(proxy_str):
    """Checks if a SOCKS5 proxy is alive by hitting a fast endpoint."""
    try:
        # Pyrogram socks5 format: socks5://ip:port
        proxy_url = f"socks5://{proxy_str}"
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.ipify.org?format=json", proxy=proxy_url, timeout=5) as resp:
                if resp.status == 200:
                    return True
    except Exception:
        pass
    return False

async def proxy_scanner_loop():
    while True:
        d = db.load_data()
        custom_proxies = d.get("custom_proxies", [])
        
        # Fetch free ones if less than 5 working
        if len(d.get("working_proxies", [])) < 5:
            log.info("Fetching new free proxies...")
            free_proxies = await fetch_free_proxies()
            
            # Combine free + custom
            all_to_check = list(set(free_proxies + custom_proxies))
            random.shuffle(all_to_check)
            
            working = []
            # Check in batches of 10
            for i in range(0, len(all_to_check), 10):
                batch = all_to_check[i:i+10]
                tasks = [check_proxy(p) for p in batch]
                results = await asyncio.gather(*tasks)
                for p, is_working in zip(batch, results):
                    if is_working:
                        working.append(p)
                        if len(working) >= 10: break # Get max 10 working
                if len(working) >= 10: break
                
            if working:
                log.info(f"Found {len(working)} working proxies.")
                d = db.load_data()
                d["working_proxies"] = working
                db.save_data(d)
        
        await asyncio.sleep(300) # Every 5 mins
