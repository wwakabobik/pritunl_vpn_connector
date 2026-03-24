---
name: vpn-connector
description: >-
  Manage Pritunl VPN connection via local HTTP service. Use when the user needs
  to connect, disconnect, or check VPN status, or when a task requires VPN access
  to reach internal resources.
---

# Pritunl VPN Connector

Local HTTP service at `http://127.0.0.1:9779` that manages Pritunl VPN with auto-TOTP.

## Prerequisites

The service must be running. Check with:

```bash
curl -s http://127.0.0.1:9779/
```

If not running, start it:

```bash
cd ~/Work/pritunl_vpn_connector && ./.venv/bin/python -m pritunl_connector.service
```

## API Reference

All calls are to `http://127.0.0.1:9779`.

### Check Status

```bash
curl -s http://127.0.0.1:9779/status
```

Response: `{"connected": true/false, "profiles": [...], "raw": "..."}`

### Connect VPN

```bash
curl -s -X POST http://127.0.0.1:9779/connect
```

Automatically generates TOTP code and starts VPN. Polls up to 15s for connection.
Response: `{"status": "connected", "profile": {...}}`

### Disconnect VPN

```bash
curl -s -X POST http://127.0.0.1:9779/disconnect
```

Response: `{"status": "disconnected", "profile_id": "..."}`

### Get Current TOTP Code

```bash
curl -s http://127.0.0.1:9779/totp
```

Response: `{"code": "123456", "remaining_seconds": 18}`

### Add VPN Profile

```bash
curl -s -X POST http://127.0.0.1:9779/profile/add
```

Registers the `.ovpn` file from config with `pritunl-client`.

### View Config

```bash
curl -s http://127.0.0.1:9779/config
```

Returns config with masked TOTP secret.

## Workflow: Ensure VPN is Connected

When a task requires VPN access (e.g., reaching internal services):

1. Check: `curl -s http://127.0.0.1:9779/status`
2. If `"connected": false`, connect: `curl -s -X POST http://127.0.0.1:9779/connect`
3. Verify: `curl -s http://127.0.0.1:9779/status`

## Troubleshooting

- **Service not running**: Start manually or re-run `setup.sh`
- **TOTP not configured**: Run `import-totp --manual SECRET` or POST to `/config/totp`
- **No profiles**: POST to `/profile/add`
- **Connection fails**: Check Pritunl app, VPN server availability, TOTP clock sync
