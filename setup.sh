#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
PLIST_NAME="com.local.pritunl-connector.plist"
PLIST_TEMPLATE="$PROJECT_DIR/$PLIST_NAME.template"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "=== Pritunl VPN Connector Setup ==="
echo ""

# 1. Virtual environment
if [ ! -f "$VENV_PYTHON" ]; then
    echo "[*] Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q poetry
fi
echo "[*] Installing dependencies via Poetry..."
POETRY_VIRTUALENVS_IN_PROJECT=true "$VENV_DIR/bin/poetry" install
echo "[OK] Dependencies installed"

# 2. Generate plist from template
echo "[*] Generating LaunchAgent plist..."
sed \
    -e "s|__VENV_PYTHON__|$VENV_PYTHON|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$PLIST_TEMPLATE" > "$PLIST_DST"
echo "[OK] Plist written to $PLIST_DST"

# 3. Ensure config exists
CONFIG_DIR="$HOME/.config/pritunl-connector"
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_DIR/config.json" <<CONF
{
  "totp_secret": "",
  "pritunl_client": "/Applications/Pritunl.app/Contents/Resources/pritunl-client",
  "profile_id": "",
  "ovpn_path": "",
  "vpn_mode": "wg",
  "host": "127.0.0.1",
  "port": 9779
}
CONF
    echo "[OK] Default config created at $CONFIG_DIR/config.json"
else
    echo "[OK] Config exists at $CONFIG_DIR/config.json"
fi

# 4. (Re)load the service
launchctl bootout "gui/$(id -u)/$PLIST_NAME" 2>/dev/null || true
sleep 1
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "[OK] Service loaded"

sleep 2

# 5. Verify
if curl -s http://127.0.0.1:9779/ > /dev/null 2>&1; then
    echo "[OK] Service is running on http://127.0.0.1:9779"
else
    echo "[!!] Service may still be starting. Check:"
    echo "     curl http://127.0.0.1:9779/"
    echo "     tail -f $PROJECT_DIR/service.log"
fi

# 6. Make Raycast scripts executable
chmod +x "$PROJECT_DIR/raycast/"*.sh 2>/dev/null || true

echo ""
echo "=== Next steps ==="
echo ""
echo "1. Import TOTP secret (pick one):"
echo "   $VENV_PYTHON -m pritunl_connector.import_totp /path/to/qr.png --save"
echo "   $VENV_PYTHON -m pritunl_connector.import_totp --manual YOUR_BASE32_SECRET"
echo ""
echo "2. Add VPN profile:"
echo "   curl -X POST http://127.0.0.1:9779/profile/add"
echo ""
echo "3. Connect:"
echo "   curl -X POST http://127.0.0.1:9779/connect"
echo ""
echo "4. Raycast: Add $PROJECT_DIR/raycast as a Script Directory in Raycast preferences."
echo ""
echo "=== Management ==="
echo "  Stop:  launchctl bootout gui/\$(id -u) $PLIST_DST"
echo "  Start: launchctl bootstrap gui/\$(id -u) $PLIST_DST"
echo "  Logs:  tail -f $PROJECT_DIR/service.log"
