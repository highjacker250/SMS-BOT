├── requirements.txt
├── config.py              # Bot token, owner ID, env vars
├── database.py            # Supabase load/save
├── firebase_utils.py      # Fetch URL, decode panel, extract no, health
├── states.py              # FSM States (sirf input lene ke liye)
│
├── utils/
│   ├── ui.py              # Small caps font, button helper
│   └── helper.py          # Cooldown check, role check (admin/owner)
│
├── core/
│   ├── scanner.py         # Background OTP scanner (sirf scanning)
│   └── start_bot.py       # Multi-bot add karne ka function
│
├── handlers/
│   ├── user.py            # User flow (Country -> Server -> Base -> Device)
│   ├── admin.py           # Admin flow (Manage servers, Ban, Analytics)
│   └── owner.py           # Owner flow (Add bot, Credits, Broadcast, Admins)
│
└── main.py                # Bot start, aiohttp web server (Render), router include
