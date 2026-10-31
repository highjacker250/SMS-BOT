import aiohttp
from bs4 import BeautifulSoup
import re, logging

log = logging.getLogger("Scraper")

async def get_smstome_countries():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://smstome.com/countries") as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                countries = {}
                for a in soup.find_all('a', href=True):
                    if '/country/' in a['href']:
                        name = a.text.strip()
                        url = f"https://smstome.com{a['href']}"
                        countries[name] = url
                return countries
    except Exception as e:
        log.error(f"Scraper Country Error: {e}")
        return {}

async def get_smstome_numbers(country_url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(country_url) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                numbers = []
                for a in soup.find_all('a', href=True):
                    if '/sms/' in a['href']:
                        num = a.text.strip()
                        if num not in numbers:
                            numbers.append(num)
                return numbers[:10] # Return top 10 numbers
    except Exception as e:
        log.error(f"Scraper Number Error: {e}")
        return []

async def get_smstome_sms(country_url, phone_number):
    try:
        # smstome URL format: https://smstome.com/country/{country}/phone/{number}
        # Let's extract base from country_url, e.g., https://smstome.com/country/united-kingdom
        base_url = country_url.rstrip('/')
        sms_url = f"{base_url}/{phone_number.replace('+', '')}" 
        # Usually it's /country/united-kingdom/447xxxxx
        
        async with aiohttp.ClientSession() as session:
            async with session.get(sms_url) as resp:
                html = await resp.text()
                soup = BeautifulSoup(html, 'html.parser')
                messages = []
                
                # Generic parsing logic for smstome (they use divs with message text)
                for div in soup.find_all('div', class_='message'):
                    sender = div.find('div', class_='sender').text.strip() if div.find('div', class_='sender') else "Unknown"
                    body = div.find('div', class_='body').text.strip() if div.find('div', class_='body') else ""
                    messages.append({"sender": sender, "message": body})
                
                return messages
    except Exception as e:
        log.error(f"Scraper SMS Error: {e}")
        return []
