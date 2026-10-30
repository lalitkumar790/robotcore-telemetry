from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"RCP1"
NONCE_BYTES = 12
KEY_BYTES = 32
MAX_LORA_PAYLOAD_BYTES = 250  # LoRa-E5 TEST-mode RX reports a 250-byte packet in the AT spec.


class PairingError(ValueError):
    pass


def load_pairing_key(path: str | os.PathLike[str]) -> bytes:
    raw = Path(path).expanduser().read_bytes()
    if len(raw) == KEY_BYTES:
        return raw
    text = raw.decode("ascii", errors="strict").strip()
    candidates: list[bytes] = []
    try:
        candidates.append(bytes.fromhex(text))
    except ValueError:
        pass
    try:
        candidates.append(base64.urlsafe_b64decode(text + "=" * (-len(text) % 4)))
    except Exception:
        pass
    for key in candidates:
        if len(key) == KEY_BYTES:
            return key
    raise PairingError("Pairing key must be 32 raw bytes, 64 hex characters, or Base64 for 32 bytes.")


def validate_descriptor(value: Any, *, now: float | None = None) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("v") != 1:
        raise PairingError("Unsupported pairing descriptor.")
    url = value.get("u")
    token = value.get("t")
    device_id = value.get("d")
    issued = value.get("i")
    expires = value.get("e")
    if not all(isinstance(x, str) and x for x in (url, token, device_id)):
        raise PairingError("Pairing descriptor is missing URL, token, or device identity.")
    if len(token) < 32 or len(token) > 128:
        raise PairingError("Pairing token length is invalid.")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".trycloudflare.com"):
        raise PairingError("Pairing URL must be an HTTPS Cloudflare Quick Tunnel hostname.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise PairingError("Pairing URL must be a clean HTTPS origin.")
    if not isinstance(issued, (int, float)) or not isinstance(expires, (int, float)):
        raise PairingError("Pairing descriptor timestamps are invalid.")
    current = time.time() if now is None else now
    if issued > current + 30 or expires <= current or expires - issued > 90:
        raise PairingError("Pairing beacon is expired or has an invalid time window.")
    if expires <= issued:
        raise PairingError("Pairing beacon expiry must follow its issue time.")
    return {
        "v": 1,
        "tunnel_url": url,
        "control_token": token,
        "device_id": device_id,
        "issued_at": int(issued),
        "valid_until": int(expires),
    }


def encode_pairing_beacon(descriptor: dict[str, Any], key: bytes) -> bytes:
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise PairingError("Pairing key must contain exactly 32 bytes.")
    normalized = validate_descriptor(descriptor)
    payload = json.dumps(
        {
            "v": 1,
            "u": normalized["tunnel_url"],
            "t": normalized["control_token"],
            "d": normalized["device_id"],
            "i": normalized["issued_at"],
            "e": normalized["valid_until"],
        },
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    nonce = os.urandom(NONCE_BYTES)
    encrypted = AESGCM(key).encrypt(nonce, payload, MAGIC)
    packet = MAGIC + nonce + encrypted
    if len(packet) > MAX_LORA_PAYLOAD_BYTES:
        raise PairingError(
            f"Encrypted pairing beacon is {len(packet)} bytes; LoRa-E5 limit is {MAX_LORA_PAYLOAD_BYTES}."
        )
    return packet


def decode_pairing_beacon(packet: bytes, key: bytes, *, now: float | None = None) -> dict[str, Any]:
    if not isinstance(packet, bytes) or not packet.startswith(MAGIC):
        raise PairingError("Not a RobotCore pairing beacon.")
    if len(packet) < len(MAGIC) + NONCE_BYTES + 16 or len(packet) > MAX_LORA_PAYLOAD_BYTES:
        raise PairingError("Pairing beacon length is invalid.")
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise PairingError("Pairing key must contain exactly 32 bytes.")
    nonce_start = len(MAGIC)
    nonce = packet[nonce_start:nonce_start + NONCE_BYTES]
    encrypted = packet[nonce_start + NONCE_BYTES:]
    try:
        plaintext = AESGCM(key).decrypt(nonce, encrypted, MAGIC)
    except Exception as exc:
        raise PairingError("Pairing beacon authentication failed.") from exc
    try:
        value = json.loads(plaintext.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PairingError("Pairing beacon payload is not valid JSON.") from exc
    return validate_descriptor(value, now=now)


def is_pairing_beacon(packet: bytes) -> bool:
    return isinstance(packet, bytes) and packet.startswith(MAGIC)
