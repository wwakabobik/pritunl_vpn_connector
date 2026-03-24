#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title VPN Status
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🌐
# @raycast.packageName Pritunl VPN

# Documentation:
# @raycast.description Check Pritunl VPN connection status

response=$(curl -s http://127.0.0.1:9779/status 2>&1)
connected=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('connected', False))" 2>/dev/null)

if [ "$connected" = "True" ]; then
    echo "VPN: Connected"
else
    echo "VPN: Disconnected"
fi
