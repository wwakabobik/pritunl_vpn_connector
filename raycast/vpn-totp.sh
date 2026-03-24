#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title VPN TOTP Code
# @raycast.mode compact

# Optional parameters:
# @raycast.icon 🔑
# @raycast.packageName Pritunl VPN

# Documentation:
# @raycast.description Get current TOTP code and copy to clipboard

response=$(curl -s http://127.0.0.1:9779/totp 2>&1)
code=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code','error'))" 2>/dev/null)
remaining=$(echo "$response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('remaining_seconds','?'))" 2>/dev/null)

if [ "$code" != "error" ]; then
    echo -n "$code" | pbcopy
    echo "TOTP: $code (${remaining}s) — copied!"
else
    echo "Error getting TOTP code"
fi
