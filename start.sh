#!/bin/bash

echo "Starting Cloudflare WARP..."
# WARP start karo aur usko accept-tos do
warp-cli --accept-tos connect || true
sleep 5

echo "Checking WARP Status..."
warp-cli status || true

echo "Starting Bot..."
python main.py
