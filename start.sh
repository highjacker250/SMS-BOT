#!/bin/bash

echo "🚀 Starting Bot..."
# Purane process kill kar taaki TelegramConflict na aaye
pkill -f "python main.py" || true
sleep 1
exec python main.py
