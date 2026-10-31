import aiohttp, logging

log = logging.getLogger("Shelex")

async def get_countries():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://otp-api.shelex.dev/api/countries") as resp:
                if resp.status == 200: return await resp.json()
    except Exception as e: log.error(f"Shelex countries error: {e}")
    return []

async def get_numbers(country):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://otp-api.shelex.dev/api/list/{country}") as resp:
                if resp.status == 200: 
                    data = await resp.json()
                    # Safe parsing if API sends dicts or strings
                    if isinstance(data, list):
                        return [str(n.get("phone", n)) if isinstance(n, dict) else str(n) for n in data]
    except Exception as e: log.error(f"Shelex numbers error: {e}")
    return []

async def get_sms(country, phone):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"https://otp-api.shelex.dev/api/{country}/{phone}") as resp:
                if resp.status == 200: return await resp.json()
    except Exception as e: log.error(f"Shelex sms error: {e}")
    return None
