#!/bin/bash

echo "Starting Cloudflare WARP in Proxy Mode..."
# WARP register karo
warp-cli --accept-tos registration new || true

# WARP ko Proxy Mode me daalo aur port 40000 set karo
warp-cli --accept-tos mode proxy || true
warp-cli --accept-tos proxy port 40000 || true

# Ab WARP connect karo
warp-cli --accept-tos connect || true

# Wait for WARP to be fully ready (up to 30 seconds)
echo "Waiting for WARP to become active..."
for i in {1..30}; do
    STATUS=$(warp-cli --accept-tos status 2>/dev/null | grep -c "Connected")
    if [ "$STATUS" -gt 0 ]; then
        echo "✅ WARP Connected in Proxy Mode on port 40000!"
        break
    fi
    sleep 1
done

echo "Starting Bot..."
python main.py
