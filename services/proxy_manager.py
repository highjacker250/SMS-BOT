# services/proxy_manager.py
import aiohttp
import random
import logging
import asyncio
import database as db

try:
    from aiohttp_socks import ProxyConnector, ProxyType
    HAS_SOCKS = True
except ImportError:
    HAS_SOCKS = False
    logging.warning("aiohttp_socks missing — proxy check will fail. Add to requirements.txt.")

log = logging.getLogger("ProxyManager")


def _make_connector(proxy_str: str):
    """SOCKS5 connector banao. Format: ip:port ya ip:port:user:pass"""
    parts = proxy_str.strip().split(":")
    if len(parts) < 2:
        return None
    ip, port = parts[0], parts[1]
    user = parts[2] if len(parts) > 2 else None
    pwd = parts[3] if len(parts) > 3 else None
    try:
        return ProxyConnector(
            proxy_type=ProxyType.SOCKS5,
            host=ip,
            port=int(port),
            username=user,
            password=pwd,
            rdns=True,
        )
    except Exception as e:
        log.debug(f"Connector build failed for {proxy_str}: {e}")
        return None


async def fetch_free_proxies():
    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt",
    ]
    proxies = []
    async with aiohttp.ClientSession() as session:
        for url in urls:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        lines = text.strip().split("\n")[:50]
                        for line in lines:
                            if ":" in line:
                                proxies.append(line.strip())
            except Exception as e:
                log.error(f"Proxy fetch error: {e}")
    return proxies


async def check_proxy(proxy_str):
    """Real internet check via SOCKS5 connector."""
    if not HAS_SOCKS:
        return False
    connector = _make_connector(proxy_str)
    if not connector:
        return False
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(
                "https://api.ipify.org?format=json", timeout=aiohttp.ClientTimeout(total=6)
            ) as resp:
                if resp.status == 200:
                    return True
    except Exception:
        pass
    return False


async def proxy_scanner_loop():
    while True:
        try:
            d = db.load_data()
            custom_proxies = d.get("custom_proxies", [])

            if len(d.get("working_proxies", [])) < 5:
                log.info("Fetching new free proxies...")
                free_proxies = await fetch_free_proxies()
                all_to_check = list(set(free_proxies + custom_proxies))
                random.shuffle(all_to_check)

                working = []
                for i in range(0, len(all_to_check), 10):
                    batch = all_to_check[i : i + 10]
                    tasks = [check_proxy(p) for p in batch]
                    results = await asyncio.gather(*tasks)
                    for p, is_working in zip(batch, results):
                        if is_working:
                            working.append(p)
                            if len(working) >= 10:
                                break
                    if len(working) >= 10:
                        break

                if working:
                    log.info(f"Found {len(working)} working proxies.")
                    d = db.load_data()
                    d["working_proxies"] = working
                    db.save_data(d)
                else:
                    log.warning("No working proxies found this cycle.")
        except Exception as e:
            log.error(f"Proxy loop error: {e}")

        await asyncio.sleep(300)
