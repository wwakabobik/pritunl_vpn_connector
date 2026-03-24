"""Pritunl VPN management HTTP service with TOTP auto-generation."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, Optional

import httpx
import pyotp
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pritunl_connector.custom_logger import get_logger, setup_logging

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "pritunl-connector" / "config.json"
PRITUNL_SOCK = "/var/run/pritunl.sock"
PRITUNL_AUTH = "/var/run/pritunl.auth"

log = get_logger(__name__)

app = FastAPI(title="Pritunl VPN Connector", version="0.1.0")

ENDPOINT_ACTIONS: dict[str, str] = {
    "/connect": "vpn_connect",
    "/disconnect": "vpn_disconnect",
    "/status": "vpn_status",
    "/totp": "get_totp",
    "/config/totp": "set_totp_secret",
    "/config": "get_config",
    "/": "health_check",
}


# ---------------------------------------------------------------------------
# Pritunl service socket client
# ---------------------------------------------------------------------------


def _read_auth_key() -> str:
    """
    Read the auth key from the pritunl-service auth file.

    :return: auth key string
    :rtype: str
    """
    return Path(PRITUNL_AUTH).read_text(encoding="utf-8").strip()


def _pritunl_headers() -> dict[str, str]:
    """
    Build request headers for the pritunl-service API.

    :return: headers dict
    :rtype: dict[str, str]
    """
    return {"Auth-Token": _read_auth_key(), "User-Agent": "pritunl"}


def _pritunl_client() -> httpx.Client:
    """
    Create an httpx client connected to the pritunl-service unix socket.

    :return: configured httpx client
    :rtype: httpx.Client
    """
    transport = httpx.HTTPTransport(uds=PRITUNL_SOCK)
    return httpx.Client(transport=transport, headers=_pritunl_headers(), timeout=10.0)


def pritunl_get(path: str) -> Any:
    """
    GET request to the pritunl-service API.

    :param path: API path (e.g. ``/profile``)
    :type path: str
    :return: parsed JSON response
    :rtype: Any
    """
    with _pritunl_client() as client:
        resp = client.get(f"http://localhost{path}")
        log.debug("pritunl GET", path=path, status=resp.status_code)
        if resp.status_code == 200 and resp.text:
            return resp.json()
        return None


def pritunl_post(path: str, data: Optional[dict[str, Any]] = None) -> Any:
    """
    POST request to the pritunl-service API.

    :param path: API path
    :type path: str
    :param data: JSON body
    :type data: Optional[dict[str, Any]]
    :return: parsed JSON response
    :rtype: Any
    """
    with _pritunl_client() as client:
        resp = client.post(f"http://localhost{path}", json=data or {})
        log.debug("pritunl POST", path=path, status=resp.status_code)
        if resp.status_code == 200 and resp.text:
            return resp.json()
        return None


def pritunl_delete(path: str, data: Optional[dict[str, Any]] = None) -> Any:
    """
    DELETE request to the pritunl-service API.

    :param path: API path
    :type path: str
    :param data: JSON body
    :type data: Optional[dict[str, Any]]
    :return: parsed JSON response
    :rtype: Any
    """
    with _pritunl_client() as client:
        resp = client.request("DELETE", f"http://localhost{path}", json=data or {})
        log.debug("pritunl DELETE", path=path, status=resp.status_code)
        if resp.status_code == 200 and resp.text:
            return resp.json()
        return None


def _get_profiles() -> dict[str, Any]:
    """
    Fetch all active profiles from pritunl-service.

    :return: dict mapping profile_id to profile data
    :rtype: dict[str, Any]
    """
    result = pritunl_get("/profile")
    if isinstance(result, dict):
        return result
    return {}


# ---------------------------------------------------------------------------
# Request logging middleware
# ---------------------------------------------------------------------------


def _identify_caller(request: Request) -> dict[str, str]:
    """
    Extract caller identity from the request.

    :param request: incoming HTTP request
    :type request: Request
    :return: dict with ``client_ip``, ``user_agent``, and ``caller``
    :rtype: dict[str, str]
    """
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")

    caller = "unknown"
    ua_lower = user_agent.lower()
    if "curl" in ua_lower:
        caller = "curl"
    elif "raycast" in ua_lower:
        caller = "raycast"
    elif "python" in ua_lower or "httpx" in ua_lower:
        caller = "python/httpx"
    elif user_agent != "unknown":
        caller = user_agent.split("/")[0]

    return {"client_ip": client_ip, "user_agent": user_agent, "caller": caller}


@app.middleware("http")
async def log_requests(request: Request, call_next) -> JSONResponse:  # type: ignore[no-untyped-def]
    """Log every incoming request with caller info, action, duration, and status."""
    start = time.monotonic()
    path = request.url.path
    method = request.method
    action = ENDPOINT_ACTIONS.get(path, path)
    caller_info = _identify_caller(request)

    log.info("Request received", action=action, method=method, path=path, **caller_info)

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log.error(
            "Request failed with exception",
            action=action,
            method=method,
            path=path,
            duration_ms=duration_ms,
            **caller_info,
            exc_info=True,
        )
        raise

    duration_ms = round((time.monotonic() - start) * 1000, 1)
    log.info(
        "Request completed",
        action=action,
        method=method,
        path=path,
        status=response.status_code,
        duration_ms=duration_ms,
        **caller_info,
    )
    return response


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _resolve_config_path() -> Path:
    """
    Resolve config path.

    Checks for a local ``config.json`` first, then falls back to ``~/.config/pritunl-connector/config.json``.

    :return: resolved config path
    :rtype: Path
    """
    local = Path(__file__).parent.parent / "config.json"
    if local.exists():
        return local
    return DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    """
    Load and return the service configuration.

    :return: configuration dictionary
    :rtype: dict[str, Any]
    """
    path = _resolve_config_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        default: dict[str, Any] = {
            "totp_secret": "",  # nosec: B105
            "profile_id": "4c8fcf04e351f2ea",
            "vpn_mode": "ovpn",
            "host": "127.0.0.1",
            "port": 9779,
        }
        save_config(default, path)
        return default
    with open(path, encoding="utf-8") as fh:
        cfg: dict[str, Any] = json.load(fh)
    return cfg


def save_config(cfg: dict[str, Any], path: Optional[Path] = None) -> None:
    """
    Persist the service configuration.

    :param cfg: configuration dictionary
    :type cfg: dict[str, Any]
    :param path: explicit path override
    :type path: Optional[Path]
    """
    target = path or _resolve_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")


def get_totp_code(secret: str) -> dict[str, Any]:
    """
    Generate current TOTP code and metadata.

    :param secret: base32-encoded TOTP secret
    :type secret: str
    :return: dict with ``code`` and ``remaining_seconds``
    :rtype: dict[str, Any]
    """
    totp = pyotp.TOTP(secret)
    code = totp.now()
    remaining = totp.interval - (int(time.time()) % totp.interval)
    return {"code": code, "remaining_seconds": remaining}


def _load_profile_conf(profile_id: str) -> dict[str, Any]:
    """
    Load the ``.conf`` sidecar for a profile from Pritunl's Application Support directory.

    :param profile_id: profile identifier
    :type profile_id: str
    :return: parsed conf data
    :rtype: dict[str, Any]
    """
    conf_path = Path.home() / "Library" / "Application Support" / "pritunl" / "profiles" / f"{profile_id}.conf"
    if not conf_path.exists():
        return {}
    with open(conf_path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


@app.get("/")
async def root() -> dict[str, str]:
    """Service health check."""
    return {"service": "pritunl-vpn-connector", "status": "running"}


@app.get("/totp")
async def totp() -> dict[str, Any]:
    """Return the current TOTP code for the configured secret."""
    cfg = load_config()
    secret = cfg.get("totp_secret", "")
    if not secret:
        raise HTTPException(status_code=400, detail="TOTP secret not configured. POST /config/totp to set it.")
    return get_totp_code(secret)


@app.get("/status")
async def status() -> dict[str, Any]:
    """Return VPN connection status from pritunl-service socket API."""
    profiles = _get_profiles()
    cfg = load_config()
    profile_id = cfg.get("profile_id", "")

    if profile_id and profile_id in profiles:
        prof = profiles[profile_id]
        return {
            "connected": prof.get("status") == "connected",
            "status": prof.get("status", "unknown"),
            "client_addr": prof.get("client_addr", ""),
            "server_addr": prof.get("server_addr", ""),
            "profile_id": profile_id,
        }

    connected = any(p.get("status") == "connected" for p in profiles.values())
    return {"connected": connected, "profiles": {pid: p.get("status") for pid, p in profiles.items()}}


@app.post("/connect")
async def connect() -> dict[str, Any]:
    """Connect VPN: auto-generate TOTP and start the profile via pritunl-service socket."""
    cfg = load_config()
    secret = cfg.get("totp_secret", "")
    if not secret:
        raise HTTPException(status_code=400, detail="TOTP secret not configured.")

    profile_id = cfg.get("profile_id", "")
    if not profile_id:
        raise HTTPException(status_code=400, detail="profile_id not set in config.")

    profiles = _get_profiles()
    if profile_id in profiles and profiles[profile_id].get("status") == "connected":
        return {"status": "already_connected", "profile": profiles[profile_id]}

    conf = _load_profile_conf(profile_id)
    if not conf:
        raise HTTPException(status_code=400, detail=f"Profile conf not found for {profile_id}.")

    otp = get_totp_code(secret)
    ovpn_path = Path.home() / "Library" / "Application Support" / "pritunl" / "profiles" / f"{profile_id}.ovpn"
    ovpn_data = ovpn_path.read_text(encoding="utf-8") if ovpn_path.exists() else ""

    mode = cfg.get("vpn_mode", "ovpn")
    server_public_key = "\n".join(conf.get("server_public_key", []))

    payload: dict[str, Any] = {
        "id": profile_id,
        "mode": mode,
        "org_id": conf.get("organization_id", ""),
        "user_id": conf.get("user_id", ""),
        "server_id": conf.get("server_id", ""),
        "sync_hosts": conf.get("sync_hosts", []),
        "sync_token": conf.get("sync_token", ""),
        "sync_secret": conf.get("sync_secret", ""),
        "data": ovpn_data,
        "username": conf.get("user", ""),
        "password": otp["code"],
        "dynamic_firewall": conf.get("dynamic_firewall", False),
        "device_auth": conf.get("device_auth", False),
        "sso_auth": conf.get("sso_auth", False),
        "server_public_key": server_public_key,
        "server_box_public_key": conf.get("server_box_public_key", ""),
        "token_ttl": conf.get("token_ttl", 2592000),
        "reconnect": not conf.get("disable_reconnect", False),
    }

    log.info("Connecting VPN", profile_id=profile_id, mode=mode, user=conf.get("user", ""))
    pritunl_post("/profile", payload)

    for _ in range(20):
        await asyncio.sleep(1)
        profiles = _get_profiles()
        if profile_id in profiles and profiles[profile_id].get("status") == "connected":
            prof = profiles[profile_id]
            log.info(
                "VPN connected",
                profile_id=profile_id,
                client_addr=prof.get("client_addr"),
                server_addr=prof.get("server_addr"),
            )
            return {"status": "connected", "profile": prof}

    profiles = _get_profiles()
    current = profiles.get(profile_id, {})
    return {"status": current.get("status", "timeout"), "profile": current}


@app.post("/disconnect")
async def disconnect() -> dict[str, Any]:
    """Disconnect VPN via pritunl-service socket."""
    cfg = load_config()
    profile_id = cfg.get("profile_id", "")

    if not profile_id:
        profiles = _get_profiles()
        if not profiles:
            return {"status": "no_profiles"}
        profile_id = next(iter(profiles))

    log.info("Disconnecting VPN", profile_id=profile_id)
    pritunl_delete(f"/profile/{profile_id}")

    for _ in range(10):
        await asyncio.sleep(0.5)
        profiles = _get_profiles()
        if profile_id not in profiles or profiles[profile_id].get("status") == "disconnected":
            log.info("VPN disconnected", profile_id=profile_id)
            return {"status": "disconnected", "profile_id": profile_id}

    return {"status": "disconnecting", "profile_id": profile_id}


class TOTPConfig(BaseModel):
    """Request body for setting the TOTP secret."""

    secret: str


@app.post("/config/totp")
async def set_totp(body: TOTPConfig) -> dict[str, Any]:
    """Set the TOTP secret in the config."""
    secret = body.secret.replace(" ", "").upper()
    try:
        pyotp.TOTP(secret).now()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid TOTP secret: {exc}") from exc

    cfg = load_config()
    cfg["totp_secret"] = secret
    save_config(cfg)
    log.info("TOTP secret updated")
    return {"status": "ok", "totp": get_totp_code(secret)}


@app.get("/config")
async def get_config() -> dict[str, Any]:
    """Return the current config (secret is masked)."""
    cfg = load_config()
    masked = {**cfg}
    if masked.get("totp_secret"):
        secret_val = masked["totp_secret"]
        masked["totp_secret"] = secret_val[:4] + "****" + secret_val[-4:] if len(secret_val) > 8 else "****"
    return masked


def main() -> None:
    """Entry point for running the service."""
    import uvicorn  # pylint: disable=import-outside-toplevel

    cfg = load_config()
    host = cfg.get("host", "127.0.0.1")
    port = cfg.get("port", 9779)

    log_file = str(Path(__file__).parent.parent / "service.log")
    setup_logging(json_logs=False, log_level="INFO", log_file=log_file)

    log.info("Starting Pritunl VPN Connector", host=host, port=port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
