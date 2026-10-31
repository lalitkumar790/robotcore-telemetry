from __future__ import annotations

import base64
import json
import os
import threading
from pathlib import Path
from typing import Any

from offline_control_protocol import encode_control_message


class PersistentControlState:
    """Crash-safe single-peer command replay state and cached ACK packet.

    Persist the receive high-water mark before command execution. Cache the
    exact encrypted reply so retries after a process restart can be answered
    without executing START/STOP twice.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.lock = threading.RLock()
        self.state: dict[str, Any] = {
            "rx_high_water": 0, "tx_counter": 0, "last_request": None,
            "last_fingerprint": None, "last_reply": None,
        }
        self._load()

    def _load(self) -> None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("state root must be an object")
            self.state = {**self.state, **value}
            for field in ("rx_high_water", "tx_counter"):
                number = self.state.get(field)
                if isinstance(number, bool) or not isinstance(number, int) or number < 0:
                    raise ValueError(f"{field} is invalid")
        except FileNotFoundError:
            return

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        with temp.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, self.path)

    @staticmethod
    def _fingerprint(message: dict[str, Any]) -> list[Any]:
        return [
            message.get("kind"), message.get("device_id"), message.get("session_id"),
            message.get("experiment_id"), message.get("counter"),
        ]

    def accept(self, message: dict[str, Any]) -> tuple[str, bytes | None]:
        """Return ('new'|'duplicate'|'rejected', cached_reply_bytes)."""
        with self.lock:
            self._load()
            request_id = message.get("request_id")
            fingerprint = self._fingerprint(message)
            if request_id == self.state.get("last_request"):
                if fingerprint == self.state.get("last_fingerprint"):
                    cached = self.state.get("last_reply")
                    return "duplicate", base64.b64decode(cached) if cached else None
                return "rejected", None
            counter = message.get("counter")
            if isinstance(counter, bool) or not isinstance(counter, int) or counter <= self.state["rx_high_water"]:
                return "rejected", None
            self.state["rx_high_water"] = counter
            self.state["last_request"] = request_id
            self.state["last_fingerprint"] = fingerprint
            self.state["last_reply"] = None
            self._save()
            return "new", None

    def reply(self, request: dict[str, Any], kind: str, key: bytes) -> bytes:
        with self.lock:
            self._load()
            if request.get("request_id") != self.state.get("last_request"):
                raise RuntimeError("Cannot reply to a command that is no longer the latest accepted request.")
            self.state["tx_counter"] += 1
            message = {
                "kind": kind, "device_id": request["device_id"],
                "request_id": request["request_id"], "counter": self.state["tx_counter"],
                "session_id": request.get("session_id") or "STATUS",
                "experiment_id": request.get("experiment_id"),
            }
            packet = encode_control_message(message, key)
            self.state["last_reply"] = base64.b64encode(packet).decode("ascii")
            self._save()
            return packet

    def cached_reply(self) -> bytes | None:
        with self.lock:
            value = self.state.get("last_reply")
            return base64.b64decode(value) if value else None
