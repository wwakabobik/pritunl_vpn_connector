# Pritunl VPN Connector

Local HTTP service for managing Pritunl VPN connections with automatic TOTP code generation.

Runs as a macOS LaunchAgent on `127.0.0.1:9779` and provides a REST API that can be used
by Cursor AI agents, Raycast commands, Spotlight (via Raycast), or plain `curl`.

## Features

- Auto-generates TOTP codes for Pritunl authentication
- HTTP API for connect / disconnect / status
- Raycast script commands for quick access via Spotlight
- Cursor AI skill for agent-driven VPN management
- macOS LaunchAgent for auto-start on login

## Setup

```bash
git clone <repo-url> ~/Work/pritunl_vpn_connector
cd ~/Work/pritunl_vpn_connector
./setup.sh
```

The setup script will:
1. Create a virtual environment and install dependencies
2. Register a LaunchAgent (auto-starts the service on login)
3. Start the service

## Import TOTP Secret

From a Google Authenticator export QR code image:

```bash
./.venv/bin/python -m pritunl_connector.import_totp /path/to/qr.png --save
```

Or set the secret manually:

```bash
./.venv/bin/python -m pritunl_connector.import_totp --manual YOUR_BASE32_SECRET
```

## API

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/status` | VPN connection status |
| `GET` | `/totp` | Current TOTP code + remaining seconds |
| `GET` | `/config` | Current config (secret masked) |
| `POST` | `/connect` | Auto-generate TOTP and connect VPN |
| `POST` | `/disconnect` | Disconnect VPN |
| `POST` | `/profile/add` | Register `.ovpn` profile with pritunl-client |
| `POST` | `/config/totp` | Set TOTP secret via JSON body |

### Quick usage

```bash
# Check status
curl http://127.0.0.1:9779/status

# Connect
curl -X POST http://127.0.0.1:9779/connect

# Disconnect
curl -X POST http://127.0.0.1:9779/disconnect

# Get TOTP code
curl http://127.0.0.1:9779/totp
```

## Raycast Integration

Add the `raycast/` directory as a Script Directory in Raycast preferences:

1. Open Raycast Settings → Extensions → Script Commands
2. Click "Add Directories" and select the `raycast/` folder
3. Commands appear as: **VPN Connect**, **VPN Disconnect**, **VPN Status**, **VPN TOTP Code**

## Cursor AI Skill

The `.cursor/skills/vpn-connector/` directory contains a skill that teaches Cursor agents
how to use this service. When the skill is active, agents can automatically connect/disconnect
VPN when tasks require access to internal resources.

## Configuration

Config lives at `~/.config/pritunl-connector/config.json`:

```json
{
  "totp_secret": "YOUR_BASE32_SECRET",
  "pritunl_client": "/Applications/Pritunl.app/Contents/Resources/pritunl-client",
  "profile_id": "",
  "ovpn_path": "/path/to/profile.ovpn",
  "vpn_mode": "wg",
  "host": "127.0.0.1",
  "port": 9779
}
```

## Service Management

```bash
# View logs
tail -f service.log

# Stop service
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.local.pritunl-connector.plist

# Start service
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.local.pritunl-connector.plist
```

## Development

```bash
# Install with dev dependencies
poetry install --with dev

# Run linters
poetry run black pritunl_connector/
poetry run ruff check --fix pritunl_connector/
poetry run pylint pritunl_connector/
poetry run mypy pritunl_connector/
poetry run pyright pritunl_connector/
poetry run bandit -q -n 5 --configfile bandit.yml -r pritunl_connector/
```
