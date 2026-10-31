from __future__ import annotations

import json
import os
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"RCC1"
KEY_BYTES = 32
NONCE_BYTES = 12
MAX_LORA_PAYLOAD_BYTES = 250
COMMANDS = {"START", "STOP", "STATUS", "ACK", "NACK"}
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")


class OfflineControlError(ValueError):
    """Invalid, unauthenticated, or replayed offline control message."""


def _identifier(value: Any, field: str, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise OfflineControlError(f"{field} must be a 1-80 character safe identifier.")
    return value


def encode_control_message(
    message: dict[str, Any],
    key: bytes,
) -> bytes:
    """Encode one authenticated control-plane message for a LoRa-E5 packet.

    Retries must retransmit the exact same packet bytes. Generate a new
    counter/request_id only for a genuinely new command.
    """
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise OfflineControlError("Control key must contain exactly 32 bytes.")
    if not isinstance(message, dict):
        raise OfflineControlError("Control message must be an object.")

    kind = message.get("kind")
    if not isinstance(kind, str) or kind not in COMMANDS:
        raise OfflineControlError("Unsupported control message kind.")
    device_id = _identifier(message.get("device_id"), "device_id")
    request_id = _identifier(message.get("request_id"), "request_id")
    counter = message.get("counter")
    if isinstance(counter, bool) or not isinstance(counter, int) or not 1 <= counter <= 0xFFFFFFFFFFFFFFFF:
        raise OfflineControlError("counter must be a positive unsigned 64-bit integer.")

    session_id = _identifier(message.get("session_id"), "session_id", required=kind not in {"STATUS"})
    experiment_id = _identifier(message.get("experiment_id"), "experiment_id", required=kind == "START")
    if kind in {"START", "STOP"} and not session_id:
        raise OfflineControlError(f"{kind} requires a session_id.")
    if kind == "START" and not experiment_id:
        raise OfflineControlError("START requires an experiment_id.")

    payload = {
        "v": 1, "k": kind, "d": device_id, "q": request_id, "n": counter,
        "s": session_id, "x": experiment_id,
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    nonce = os.urandom(NONCE_BYTES)
    packet = MAGIC + nonce + AESGCM(key).encrypt(nonce, raw, MAGIC)
    if len(packet) > MAX_LORA_PAYLOAD_BYTES:
        raise OfflineControlError(f"Control packet exceeds {MAX_LORA_PAYLOAD_BYTES}-byte LoRa-E5 limit.")
    return packet


def decode_control_message(packet: bytes, key: bytes) -> dict[str, Any]:
    if not isinstance(packet, bytes) or not packet.startswith(MAGIC):
        raise OfflineControlError("Not a RobotCore offline-control packet.")
    if len(packet) < len(MAGIC) + NONCE_BYTES + 16 or len(packet) > MAX_LORA_PAYLOAD_BYTES:
        raise OfflineControlError("Offline-control packet length is invalid.")
    if not isinstance(key, bytes) or len(key) != KEY_BYTES:
        raise OfflineControlError("Control key must contain exactly 32 bytes.")
    nonce = packet[len(MAGIC):len(MAGIC) + NONCE_BYTES]
    try:
        raw = AESGCM(key).decrypt(nonce, packet[len(MAGIC) + NONCE_BYTES:], MAGIC)
        value = json.loads(raw.decode("ascii"))
    except Exception as exc:
        raise OfflineControlError("Control packet authentication or payload validation failed.") from exc
    if not isinstance(value, dict) or value.get("v") != 1 or not isinstance(value.get("k"), str) or value.get("k") not in COMMANDS:
        raise OfflineControlError("Unsupported offline-control message.")
    result = {
        "kind": value.get("k"),
        "device_id": _identifier(value.get("d"), "device_id"),
        "request_id": _identifier(value.get("q"), "request_id"),
        "counter": value.get("n"),
        "session_id": _identifier(value.get("s"), "session_id", required=value.get("k") not in {"STATUS"}),
        "experiment_id": _identifier(value.get("x"), "experiment_id", required=value.get("k") == "START"),
    }
    if isinstance(result["counter"], bool) or not isinstance(result["counter"], int) or not 1 <= result["counter"] <= 0xFFFFFFFFFFFFFFFF:
        raise OfflineControlError("Control counter is invalid.")
    if result["kind"] in {"START", "STOP"} and not result["session_id"]:
        raise OfflineControlError("Session command is missing session_id.")
    if result["kind"] == "START" and not result["experiment_id"]:
        raise OfflineControlError("START is missing experiment_id.")
    return result


@dataclass(frozen=True)
class ReplayDecision:
    accepted: bool
    duplicate: bool
    reason: str


class ControlReplayGuard:
    """Monotonic-counter replay guard; persist high_water on the receiving device.

    The bounded request cache makes an identical retry idempotent during the
    process lifetime. After reboot, callers should persist both high_water and
    the active session/request record if they need duplicate-ACK recovery.
    """
    def __init__(self, high_water: int = 0, cache_size: int = 128):
        if isinstance(high_water, bool) or not isinstance(high_water, int) or high_water < 0:
            raise ValueError("high_water must be a non-negative integer")
        if cache_size < 1:
            raise ValueError("cache_size must be positive")
        self.high_water = high_water
        self.cache_size = cache_size
        self._seen: OrderedDict[str, tuple[int, tuple[Any, ...]]] = OrderedDict()

    def accept(self, message: dict[str, Any]) -> ReplayDecision:
        try:
            request_id = _identifier(message.get("request_id"), "request_id")
            counter = message.get("counter")
            if isinstance(counter, bool) or not isinstance(counter, int) or counter < 1:
                raise OfflineControlError("Invalid counter.")
            fingerprint = (
                message.get("kind"), message.get("device_id"),
                message.get("session_id"), message.get("experiment_id"),
            )
        except (AttributeError, OfflineControlError) as exc:
            return ReplayDecision(False, False, str(exc))

        previous = self._seen.get(request_id)
        if previous is not None:
            if previous == (counter, fingerprint):
                self._seen.move_to_end(request_id)
                return ReplayDecision(True, True, "identical_retry")
            return ReplayDecision(False, False, "request_id_reused_with_different_content")
        if counter <= self.high_water:
            return ReplayDecision(False, False, "stale_or_replayed_counter")

        self.high_water = counter
        self._seen[request_id] = (counter, fingerprint)
        while len(self._seen) > self.cache_size:
            self._seen.popitem(last=False)
        return ReplayDecision(True, False, "new_command")
