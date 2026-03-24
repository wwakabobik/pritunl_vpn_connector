#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title VPN Disconnect
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🔓
# @raycast.packageName Pritunl VPN

# Documentation:
# @raycast.description Disconnect from Pritunl VPN

response=$(curl -s -X POST http://127.0.0.1:9779/disconnect 2>&1)
status=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','error'))" 2>/dev/null)

echo "VPN: $status"
