"""Import TOTP secret from Google Authenticator export QR code or manual entry."""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Optional

import pyotp

CONFIG_SEARCH_PATHS = [
    Path(__file__).parent.parent / "config.json",
    Path.home() / ".config" / "pritunl-connector" / "config.json",
]


def _find_config() -> Path:
    """
    Find the config file.

    :return: path to the config file
    :rtype: Path
    """
    for candidate in CONFIG_SEARCH_PATHS:
        if candidate.exists():
            return candidate
    return CONFIG_SEARCH_PATHS[0]


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    """
    Read a varint from protobuf data.

    :param data: raw bytes
    :type data: bytes
    :param pos: current position
    :type pos: int
    :return: decoded value and new position
    :rtype: tuple[int, int]
    """
    result = 0
    shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            break
        shift += 7
    return result, pos


def _read_tag(data: bytes, pos: int) -> tuple[int, int, int]:
    """
    Read a protobuf field tag.

    :param data: raw bytes
    :type data: bytes
    :param pos: current position
    :type pos: int
    :return: field number, wire type, new position
    :rtype: tuple[int, int, int]
    """
    varint, pos = _read_varint(data, pos)
    return varint >> 3, varint & 0x07, pos


def _parse_otp_entry(data: bytes) -> dict[str, Any]:
    """
    Parse a single OTP entry from protobuf.

    :param data: raw protobuf message bytes
    :type data: bytes
    :return: parsed entry
    :rtype: dict[str, Any]
    """
    pos = 0
    entry: dict[str, Any] = {"secret_raw": b"", "name": "", "issuer": "", "type": 2}  # nosec: B105
    while pos < len(data):
        field_num, wire_type, pos = _read_tag(data, pos)
        if wire_type == 2:
            length, pos = _read_varint(data, pos)
            chunk = data[pos : pos + length]
            pos += length
            if field_num == 1:
                entry["secret_raw"] = chunk
            elif field_num == 2:
                entry["name"] = chunk.decode("utf-8", errors="replace")
            elif field_num == 4:
                entry["issuer"] = chunk.decode("utf-8", errors="replace")
        elif wire_type == 0:
            val, pos = _read_varint(data, pos)
            if field_num == 6:
                entry["type"] = val
    entry["secret_b32"] = base64.b32encode(entry["secret_raw"]).decode("ascii").rstrip("=")
    return entry


def parse_migration_payload(data_b64: str) -> list[dict[str, Any]]:
    """
    Parse Google Authenticator ``otpauth-migration`` protobuf payload.

    :param data_b64: base64-encoded protobuf data
    :type data_b64: str
    :return: list of OTP entries
    :rtype: list[dict[str, Any]]
    """
    raw = base64.b64decode(data_b64)
    results: list[dict[str, Any]] = []
    pos = 0
    while pos < len(raw):
        field_num, wire_type, pos = _read_tag(raw, pos)
        if wire_type == 2:
            length, pos = _read_varint(raw, pos)
            chunk = raw[pos : pos + length]
            pos += length
            if field_num == 1:
                results.append(_parse_otp_entry(chunk))
        elif wire_type == 0:
            _, pos = _read_varint(raw, pos)
        else:
            break
    return results


def decode_qr_image(image_path: str) -> list[dict[str, Any]]:
    """
    Decode QR code(s) from an image and extract OTP entries.

    :param image_path: path to the QR code image
    :type image_path: str
    :return: list of OTP entries
    :rtype: list[dict[str, Any]]
    """
    from PIL import Image  # pylint: disable=import-outside-toplevel
    from pyzbar.pyzbar import decode as qr_decode  # pylint: disable=import-outside-toplevel

    img = Image.open(image_path)
    qr_results = qr_decode(img)
    if not qr_results:
        print("ERROR: No QR code found in the image.", file=sys.stderr)
        sys.exit(1)

    all_entries: list[dict[str, Any]] = []
    for qr_item in qr_results:
        uri = qr_item.data.decode("utf-8")

        if uri.startswith("otpauth-migration://"):
            parsed = urllib.parse.urlparse(uri)
            params = urllib.parse.parse_qs(parsed.query)
            data_b64 = params.get("data", [""])[0]
            all_entries.extend(parse_migration_payload(data_b64))

        elif uri.startswith("otpauth://totp/"):
            parsed = urllib.parse.urlparse(uri)
            params = urllib.parse.parse_qs(parsed.query)
            all_entries.append(
                {
                    "secret_b32": params.get("secret", [""])[0],
                    "name": urllib.parse.unquote(parsed.path.lstrip("/")),
                    "issuer": params.get("issuer", [""])[0],
                    "type": 2,
                }
            )

    return all_entries


def print_entries(entries: list[dict[str, Any]]) -> None:
    """
    Print discovered OTP entries with current codes.

    :param entries: list of OTP entries
    :type entries: list[dict[str, Any]]
    """
    print(f"\nFound {len(entries)} account(s):\n")
    for i, entry in enumerate(entries, 1):
        otp_type = "TOTP" if entry["type"] == 2 else "HOTP"
        print(f"  [{i}] {entry['issuer']} \u2014 {entry['name']}")
        print(f"      Type:   {otp_type}")
        print(f"      Secret: {entry['secret_b32']}")
        if otp_type == "TOTP":
            totp = pyotp.TOTP(entry["secret_b32"])
            remaining = totp.interval - (int(time.time()) % totp.interval)
            print(f"      OTP:    {totp.now()} (valid for {remaining}s)")
        print()


def save_secret(secret: str, config_path: Optional[Path] = None) -> None:
    """
    Save a TOTP secret to the service config.

    :param secret: base32 TOTP secret
    :type secret: str
    :param config_path: explicit path override
    :type config_path: Optional[Path]
    """
    target = config_path or _find_config()
    with open(target, encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg["totp_secret"] = secret
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
        fh.write("\n")
    print(f"  -> Saved to {target}")


def main() -> None:
    """CLI entry point for importing TOTP secrets."""
    parser = argparse.ArgumentParser(description="Import TOTP secret from Google Authenticator QR export")
    parser.add_argument("image", nargs="?", help="Path to QR code image")
    parser.add_argument("--save", action="store_true", help="Save the secret to config.json")
    parser.add_argument("--index", type=int, default=1, help="Which entry to save (1-based, default: 1)")
    parser.add_argument("--manual", type=str, help="Set a base32 TOTP secret directly (no QR needed)")
    args = parser.parse_args()

    if args.manual:
        secret = args.manual.replace(" ", "").upper()
        try:
            totp = pyotp.TOTP(secret)
            remaining = totp.interval - (int(time.time()) % totp.interval)
            print(f"  Secret: {secret}")
            print(f"  OTP:    {totp.now()} (valid for {remaining}s)")
        except Exception as exc:
            print(f"ERROR: Invalid secret: {exc}", file=sys.stderr)
            sys.exit(1)
        save_secret(secret)
        return

    if not args.image:
        parser.print_help()
        sys.exit(1)

    entries = decode_qr_image(args.image)
    if not entries:
        print("No OTP entries found.", file=sys.stderr)
        sys.exit(1)

    print_entries(entries)

    if args.save:
        idx = args.index - 1
        if idx < 0 or idx >= len(entries):
            print(f"ERROR: --index {args.index} is out of range (1..{len(entries)})", file=sys.stderr)
            sys.exit(1)
        chosen = entries[idx]
        print(f"  Saving entry [{args.index}]: {chosen['issuer']} \u2014 {chosen['name']}")
        save_secret(chosen["secret_b32"])


if __name__ == "__main__":
    main()
