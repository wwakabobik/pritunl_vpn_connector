#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title VPN Connect
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🔒
# @raycast.packageName Pritunl VPN

# Documentation:
# @raycast.description Connect to Pritunl VPN (auto-generates TOTP)

response=$(curl -s -X POST http://127.0.0.1:9779/connect 2>&1)
status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','error'))" 2>/dev/null)

if [ "$status" = "connected" ] || [ "$status" = "already_connected" ]; then
    echo "VPN connected"
else
    echo "VPN: $status"
fi
