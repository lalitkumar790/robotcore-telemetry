from __future__ import annotations

import hmac
import os
import queue
import re
import secrets
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from config import RadioConfig
from device_discovery import select_serial_port
from pairing_protocol import encode_pairing_beacon, load_pairing_key
from radio import LoRaE5

URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


class TunnelPairingAnnouncer(threading.Thread):
    """Wait for internet, open a temporary HTTPS tunnel, and announce it over encrypted LoRa."""

    def __init__(self, *, local_port: int = 8766) -> None:
        super().__init__(daemon=True, name="RobotCoreTunnelPairingAnnouncer")
        self.local_port = local_port
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.lock = threading.RLock()
        self.state = "starting"
        self.internet_ok = False
        self.tunnel_state = "not_started"
        self.beacon_state = "waiting"
        self.tunnel_url: str | None = None
        self._stable_control_token = secrets.token_urlsafe(32)
        self.control_token: str | None = self._stable_control_token
        self.device_id = os.getenv("ROBOTCORE_DEVICE_ID", "").strip() or ("pi-" + uuid.uuid4().hex[:12])
        self.last_beacon_at: float | None = None
        self.last_beacon_outcome: str | None = None
        self.last_error: str | None = None
        self._radio: LoRaE5 | None = None
        self._tunnel: subprocess.Popen | None = None
        self._tunnel_output: queue.Queue[str] = queue.Queue()
        self._reader: threading.Thread | None = None
        self._pairing_key: bytes | None = None
        self._cloudflared = os.getenv("ROBOTCORE_CLOUDFLARED_BIN", "cloudflared").strip() or "cloudflared"
        self._probe_interval = max(5.0, float(os.getenv("ROBOTCORE_INTERNET_PROBE_INTERVAL", "10")))
        self._beacon_interval = max(5.0, float(os.getenv("ROBOTCORE_PAIRING_BEACON_INTERVAL", "12")))
        self._last_probe = 0.0
        self._last_beacon = 0.0
        self._last_radio_retry = 0.0

    def status(self) -> dict[str, Any]:
        with self.lock:
            age = None if self.last_beacon_at is None else max(0.0, time.time() - self.last_beacon_at)
            return {
                "state": self.state,
                "internet_connected": self.internet_ok,
                "tunnel_state": self.tunnel_state,
                "tunnel_url": self.tunnel_url,
                "beacon_state": self.beacon_state,
                "device_id": self.device_id,
                "last_beacon_age_s": age,
                "last_beacon_outcome": self.last_beacon_outcome,
                "last_error": self.last_error,
                "paused_for_recording": self.pause_event.is_set(),
                "pairing_key_configured": self._pairing_key is not None,
            }

    def authorize(self, header: str | None) -> bool:
        value = (header or "").strip()
        if value.lower().startswith("bearer "):
            value = value[7:].strip()
        if not value:
            return False
        with self.lock:
            token = self.control_token
        return bool(token) and hmac.compare_digest(value, token)

    def pause_for_recording(self, timeout_s: float = 15.0) -> bool:
        self.pause_event.set()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            with self.lock:
                closed = self._radio is None
            if closed:
                return True
            time.sleep(0.05)
        return False

    def resume_after_recording(self) -> None:
        self.pause_event.clear()

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=8.0)
        self._close_radio()
        self._stop_tunnel()

    def _set(self, **values: Any) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def _probe_internet(self) -> bool:
        import urllib.request

        request = urllib.request.Request(
            "https://www.cloudflare.com/cdn-cgi/trace",
            headers={"User-Agent": "RobotCore-FieldAgent/1.0"},
        )
        try:
            with urllib.request.urlopen(request, timeout=5.0) as response:
                return 200 <= response.status < 400
        except Exception as exc:
            self._set(last_error=f"Internet probe: {type(exc).__name__}: {exc}")
            return False

    def _reader_loop(self, process: subprocess.Popen) -> None:
        stream = process.stdout
        if stream is None:
            return
        try:
            for line in stream:
                self._tunnel_output.put(line.rstrip())
        except Exception as exc:
            self._tunnel_output.put(f"[reader] {type(exc).__name__}: {exc}")

    def _start_tunnel(self) -> bool:
        binary = shutil.which(self._cloudflared)
        if not binary:
            self._set(
                tunnel_state="cloudflared_missing",
                state="waiting_for_cloudflared",
                last_error=f"cloudflared executable not found: {self._cloudflared}",
            )
            return False
        command = [
            binary, "tunnel", "--url", f"http://127.0.0.1:{self.local_port}",
            "--no-autoupdate", "--protocol", "http2", "--output", "json",
        ]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._set(
                tunnel_state="start_failed",
                state="waiting_to_retry",
                last_error=f"Could not start cloudflared: {type(exc).__name__}: {exc}",
            )
            return False

        self._tunnel = process
        self._tunnel_output = queue.Queue()
        self._reader = threading.Thread(
            target=self._reader_loop, args=(process,), daemon=True,
            name="RobotCoreCloudflaredOutput",
        )
        self._reader.start()
        self._set(tunnel_state="connecting", state="connecting_tunnel", tunnel_url=None, control_token=self._stable_control_token, last_error=None)

        deadline = time.monotonic() + 60.0
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            if process.poll() is not None:
                self._set(
                    tunnel_state="exited",
                    state="waiting_to_retry",
                    last_error=f"cloudflared exited with code {process.returncode} before publishing a URL.",
                )
                self._stop_tunnel()
                return False
            try:
                line = self._tunnel_output.get(timeout=0.5)
            except queue.Empty:
                continue
            match = URL_RE.search(line)
            if not match:
                continue
            url = match.group(0).rstrip(".,;)")
            token = self._stable_control_token
            self._set(
                tunnel_url=url,
                control_token=token,
                tunnel_state="ready",
                state="announcing",
                last_error=None,
            )
            return True

        self._set(
            tunnel_state="timeout",
            state="waiting_to_retry",
            last_error="Timed out waiting 60 seconds for cloudflared to publish its trycloudflare.com URL.",
        )
        self._stop_tunnel()
        return False

    def _stop_tunnel(self) -> None:
        process = self._tunnel
        self._tunnel = None
        if process is not None and process.poll() is None:
            try:
                process.terminate()
                process.wait(timeout=4)
            except Exception:
                try:
                    process.kill()
                except Exception:
                    pass
        with self.lock:
            self.tunnel_url = None
            self.control_token = self._stable_control_token
            if self.tunnel_state not in {"cloudflared_missing", "not_started"}:
                self.tunnel_state = "stopped"

    def _close_radio(self) -> None:
        with self.lock:
            radio = self._radio
            self._radio = None
        if radio is not None:
            try:
                radio.close()
            except Exception:
                pass

    def _ensure_radio(self) -> bool:
        with self.lock:
            if self._radio is not None:
                return True
        try:
            port = select_serial_port("lora")
            radio = LoRaE5(port, RadioConfig())
            radio.enter_test_mode()
            confirmed, response = radio.configure()
            if not confirmed:
                radio.close()
                raise RuntimeError("LoRa-E5 radio configuration not acknowledged: " + (response or "no response"))
            with self.lock:
                if self.pause_event.is_set() or self.stop_event.is_set():
                    radio.close()
                    return False
                self._radio = radio
            self._set(beacon_state="ready", last_error=None)
            return True
        except Exception as exc:
            self._set(
                beacon_state="retrying",
                last_error=f"LoRa pairing radio: {type(exc).__name__}: {exc}",
            )
            return False

    def _send_beacon(self) -> None:
        with self.lock:
            radio = self._radio
            url = self.tunnel_url
            token = self.control_token
            key = self._pairing_key
        if radio is None or not url or not token or key is None:
            return
        now = int(time.time())
        descriptor = {
            "v": 1,
            "u": url,
            "t": token,
            "d": self.device_id,
            "i": now,
            "e": now + 45,
        }
        try:
            packet = encode_pairing_beacon(descriptor, key)
            outcome, response = radio.transmit(packet, timeout_s=8.0)
            self._set(
                beacon_state="announced" if outcome == "confirmed" else "retrying",
                last_beacon_at=time.time(),
                last_beacon_outcome=outcome,
                last_error=None if outcome == "confirmed" else "LoRa pairing TX " + outcome + ": " + response[-300:],
            )
        except Exception as exc:
            self._set(
                beacon_state="retrying",
                last_error=f"LoRa pairing beacon: {type(exc).__name__}: {exc}",
            )
            self._close_radio()

    def run(self) -> None:
        key_path = os.getenv("ROBOTCORE_PAIRING_KEY_FILE", "/etc/robotcore-pairing.key")
        try:
            self._pairing_key = load_pairing_key(key_path)
        except Exception as exc:
            self._set(
                state="pairing_key_missing",
                beacon_state="disabled",
                last_error=f"Encrypted LoRa pairing is not provisioned: {exc}",
            )

        while not self.stop_event.is_set():
            if self._pairing_key is None:
                self._set(
                    state="pairing_key_missing",
                    beacon_state="disabled",
                    tunnel_state="not_started",
                )
                self.stop_event.wait(5.0)
                continue

            if self.pause_event.is_set():
                self._close_radio()
                self._set(state="recording", beacon_state="paused_for_recording")
                self.stop_event.wait(0.25)
                continue

            if self._tunnel is not None and self._tunnel.poll() is not None:
                code = self._tunnel.returncode
                self._stop_tunnel()
                self._set(state="waiting_for_internet", tunnel_state="exited", last_error=f"cloudflared exited with code {code}.")

            if self.tunnel_url is None:
                now = time.monotonic()
                if now - self._last_probe >= self._probe_interval:
                    self._last_probe = now
                    self._set(state="checking_internet", tunnel_state="waiting_for_internet")
                    online = self._probe_internet()
                    self._set(internet_ok=online)
                    if online:
                        self._start_tunnel()
                    else:
                        self._set(state="waiting_for_internet")
                self.stop_event.wait(0.5)
                continue

            if not self._ensure_radio():
                self.stop_event.wait(3.0)
                continue

            now = time.monotonic()
            if now - self._last_beacon >= self._beacon_interval:
                self._last_beacon = now
                self._send_beacon()
            self._set(state="announcing")
            self.stop_event.wait(0.5)

        self._close_radio()
        self._stop_tunnel()
        self._set(state="stopped", beacon_state="stopped", tunnel_state="stopped")


if __name__ == "__main__":
    raise SystemExit("Import TunnelPairingAnnouncer from field_agent.py; do not launch it separately.")
