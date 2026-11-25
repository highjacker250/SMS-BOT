# services/paypal_api.py
import aiohttp
import base64
import logging
import config

log = logging.getLogger("PayPalAPI")

async def get_paypal_access_token():
    """PayPal OAuth API se Access Token generate karta hai"""
    url = "https://api-m.sandbox.paypal.com/v1/oauth2/token" if config.PAYPAL_MODE == "sandbox" else "https://api-m.paypal.com/v1/oauth2/token"
    
    auth_str = f"{config.PAYPAL_CLIENT_ID}:{config.PAYPAL_SECRET}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()
    
    headers = {
        "Accept": "application/json",
        "Accept-Language": "en_US",
        "Authorization": f"Basic {b64_auth}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {"grant_type": "client_credentials"}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, timeout=10) as resp:
                if resp.status == 200:
                    json_data = await resp.json()
                    return json_data.get("access_token")
                else:
                    log.error(f"PayPal API Error: {await resp.text()}")
                    return None
    except Exception as e:
        log.error(f"PayPal API Exception: {e}")
        return None
