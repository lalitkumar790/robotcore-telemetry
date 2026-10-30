from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import uvicorn

from config import IMU_ADDRESS, IMU_NAME_HINT, MISSIONS_DIR
from device_discovery import select_serial_port, serial_candidates
from config import GPS_VID_PID, LORA_VID_PID

PI_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PI_DIR.parent / "common"))
from pairing_announcer import TunnelPairingAnnouncer

MISSIONS_PATH = Path(MISSIONS_DIR).expanduser()
if not MISSIONS_PATH.is_absolute():
    MISSIONS_PATH = (PI_DIR / MISSIONS_PATH).resolve()
CONSOLE_TOKEN = os.getenv("ROBOTCORE_FIELD_CONTROL_TOKEN", "").strip()
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def valid_id(value: str) -> bool:
    return bool(ID_RE.fullmatch(value or ""))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("._-")[:80] or "session"


def _authorized(header: str | None) -> bool:
    value = (header or "").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if not value:
        return False
    import hmac
    return (bool(CONSOLE_TOKEN) and hmac.compare_digest(value, CONSOLE_TOKEN)) or ANNOUNCER.authorize("Bearer " + value)


class StartRequest(BaseModel):
    experiment_id: str = Field(min_length=3, max_length=80)
    session_id: str = Field(min_length=3, max_length=80)


class FieldController:
    def __init__(self, announcer: TunnelPairingAnnouncer) -> None:
        self.announcer = announcer
        self.lock = threading.RLock()
        self.process: subprocess.Popen | None = None
        self.log_handle = None
        self.log_path: Path | None = None
        self.session_id: str | None = None
        self.experiment_id: str | None = None
        self.started_at: str | None = None
        self.ended_at: str | None = None
        self.last_exit_code: int | None = None
        self.state = "idle"
        self.last_error: str | None = None

    def _close_log_if_done(self) -> None:
        if self.process is not None and self.process.poll() is not None:
            self.last_exit_code = self.process.returncode
            if self.state not in {"stopping", "stopped"}:
                self.state = "stopped" if self.process.returncode == 0 else "failed"
            self.ended_at = self.ended_at or _utc_now()
            if self.log_handle:
                self.log_handle.close()
                self.log_handle = None
            if self.state in {"failed", "stopped"}:
                self.announcer.resume_after_recording()

    def _tail(self, limit: int = 30) -> list[str]:
        if not self.log_path or not self.log_path.exists():
            return []
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return lines[-limit:]
        except OSError as exc:
            return ["Unable to read session log: " + str(exc)]

    def _stage(self, running: bool, lines: list[str]) -> str:
        joined = "\n".join(lines)
        if not running:
            return self.state
        if "[TX " in joined:
            return "recording"
        if "[GPS] Waiting for a valid RMC fix" in joined or "[GPS] No valid fix yet" in joined:
            return "waiting_gps_fix"
        if "[IMU] Preflight: waiting" in joined or "fresh WT901BLE68 reading" in joined:
            return "waiting_imu"
        if "[LoRa] Test mode response" in joined or "[LoRa] Config response" in joined:
            return "starting"
        return "starting"

    def status(self) -> dict[str, Any]:
        with self.lock:
            self._close_log_if_done()
            running = self.process is not None and self.process.poll() is None
            lines = self._tail()
            stage = self._stage(running, lines)
            files: list[dict[str, Any]] = []
            if self.session_id and MISSIONS_PATH.exists():
                needle = _safe_name(self.session_id)
                for f in sorted(MISSIONS_PATH.glob("*" + needle + "*")):
                    if f.is_file() and f.suffix in {".rcm", ".jsonl", ".json"}:
                        files.append({"name": f.name, "size_bytes": f.stat().st_size})
            return {
                "state": "running" if running else self.state,
                "stage": stage,
                "session_id": self.session_id,
                "experiment_id": self.experiment_id,
                "started_at": self.started_at,
                "ended_at": self.ended_at,
                "exit_code": self.last_exit_code,
                "last_error": self.last_error,
                "log_file": str(self.log_path) if self.log_path else None,
                "log_tail": lines,
                "mission_files": files,
                "connection": self.announcer.status(),
            }

    def start(self, experiment_id: str, session_id: str) -> dict[str, Any]:
        with self.lock:
            self._close_log_if_done()
            if self.process is not None and self.process.poll() is None:
                raise HTTPException(status_code=409, detail="A field session is already running.")
            if not valid_id(experiment_id) or not valid_id(session_id):
                raise HTTPException(status_code=422, detail="Experiment and session IDs may contain letters, numbers, dots, underscores and dashes only.")
            if not self.announcer.pause_for_recording():
                raise HTTPException(status_code=503, detail="Could not release the LoRa radio from pairing mode. Check the Pi connection status and retry.")
            MISSIONS_PATH.mkdir(parents=True, exist_ok=True)
            log_path = MISSIONS_PATH / ("session_" + _safe_name(session_id) + ".log")
            if log_path.exists():
                self.announcer.resume_after_recording()
                raise HTTPException(status_code=409, detail="This session ID already has a Pi run log. Generate a new session.")
            env = os.environ.copy()
            env["ROBOTCORE_EXPERIMENT_ID"] = experiment_id
            env["ROBOTCORE_SESSION_ID"] = session_id
            env["ROBOTCORE_MISSIONS_DIR"] = str(MISSIONS_PATH)
            if IMU_ADDRESS:
                env["ROBOTCORE_IMU_ADDRESS"] = IMU_ADDRESS
            try:
                handle = log_path.open("x", encoding="utf-8", buffering=1)
            except Exception:
                self.announcer.resume_after_recording()
                raise
            command = [
                sys.executable, str(PI_DIR / "runner.py"),
                "--require-lora", "--imu-startup-timeout", "120",
            ]
            try:
                process = subprocess.Popen(
                    command, cwd=str(PI_DIR), env=env,
                    stdout=handle, stderr=subprocess.STDOUT,
                    text=True, start_new_session=True,
                )
            except Exception:
                handle.close()
                self.announcer.resume_after_recording()
                raise
            self.process = process
            self.log_handle = handle
            self.log_path = log_path
            self.session_id = session_id
            self.experiment_id = experiment_id
            self.started_at = _utc_now()
            self.ended_at = None
            self.last_exit_code = None
            self.last_error = None
            self.state = "starting"
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self.lock:
            process = self.process
            if process is None or process.poll() is not None:
                self._close_log_if_done()
                return self.status()
            self.state = "stopping"
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                pass
        try:
            process.wait(timeout=45)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        with self.lock:
            self._close_log_if_done()
            if self.last_exit_code == 0:
                self.state = "stopped"
            elif self.last_exit_code is not None:
                self.state = "failed"
            self.ended_at = self.ended_at or _utc_now()
            self.announcer.resume_after_recording()
            return self.status()


ANNOUNCER = TunnelPairingAnnouncer()
controller = FieldController(ANNOUNCER)
app = FastAPI(title="RobotCore Local Field Console", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://robotcore-telemetry.vercel.app"],
    allow_origin_regex=r"^http://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2[0-9]|3[01])(?:\.\d{1,3}){2})(?::\d+)?$",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,
)


@app.on_event("startup")
def startup_event() -> None:
    if not ANNOUNCER.is_alive():
        ANNOUNCER.start()


@app.get("/", include_in_schema=False)
@app.get("/field-console", include_in_schema=False)
def field_console() -> FileResponse:
    return FileResponse(PI_DIR / "field-console.html")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "robotcore-field-console"}


async def run_preflight() -> dict[str, Any]:
    ports = serial_candidates()
    gps = {"ok": False, "status": "missing", "device": None, "detail": "GPS USB adapter not detected."}
    lora = {"ok": False, "status": "missing", "device": None, "detail": "LoRa-E5 USB adapter not detected."}
    try:
        chosen_gps = select_serial_port("gps")
        gps = {"ok": True, "status": "ready", "device": chosen_gps, "detail": "GPS USB serial adapter detected; a valid outdoor fix is checked during start."}
    except Exception as exc:
        gps["detail"] = str(exc)
    try:
        chosen_gps = gps.get("device") if gps["ok"] else None
        chosen_lora = select_serial_port("lora", exclude={chosen_gps} if chosen_gps else set())
        lora = {"ok": True, "status": "ready", "device": chosen_lora, "detail": "LoRa-E5 USB adapter detected. Radio configuration is verified when the transmitter starts."}
    except Exception as exc:
        lora["detail"] = str(exc)

    imu = {"ok": False, "status": "missing", "device": None, "rssi": None, "detail": "WitMotion WT901BLE68 not discovered yet."}
    try:
        from bleak import BleakScanner
        devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
        wanted = (IMU_ADDRESS or "").replace(":", "").replace("-", "").casefold()
        matches = []
        for _key, pair in devices.items():
            device, advertisement = pair
            address = (getattr(device, "address", "") or "").replace(":", "").replace("-", "").casefold()
            name = getattr(device, "name", None) or getattr(advertisement, "local_name", None) or "(name unavailable)"
            if (wanted and address == wanted) or IMU_NAME_HINT.casefold() in name.casefold() or "wt901" in name.casefold() or "witmotion" in name.casefold():
                matches.append((name, getattr(device, "address", None), getattr(advertisement, "rssi", None)))
        if matches:
            name, address, rssi = sorted(matches, key=lambda m: m[2] if isinstance(m[2], int) else -200, reverse=True)[0]
            imu = {"ok": True, "status": "ready", "device": address or name, "rssi": rssi, "detail": f"{name} discovered; fresh decoded BLE data is checked by transmitter preflight."}
        else:
            imu["detail"] = f"No WitMotion device found. Expected address/name: {IMU_ADDRESS or IMU_NAME_HINT}."
    except Exception as exc:
        imu["detail"] = "BLE scan failed: " + str(exc)

    checks = {"gps": gps, "lora": lora, "imu": imu}
    return {
        "ok": all(value["ok"] for value in checks.values()),
        "checked_at": _utc_now(),
        "checks": checks,
        "serial_devices": [
            {
                "device": c.device,
                "description": c.description,
                "vid_pid": f"{c.vid:04X}:{c.pid:04X}" if c.vid is not None and c.pid is not None else "unknown",
            }
            for c in ports
        ],
    }


@app.get("/api/preflight")
async def preflight(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Field-console token is missing or invalid.")
    return await run_preflight()


@app.get("/api/connection")
def connection_status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Field-console token is missing or invalid.")
    return ANNOUNCER.status()


@app.get("/api/status")
def status(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Field-console token is missing or invalid.")
    return controller.status()


@app.post("/api/session/start")
async def start_session(body: StartRequest, authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Field console token is missing or invalid.")
    if not valid_id(body.experiment_id) or not valid_id(body.session_id):
        raise HTTPException(status_code=422, detail="Invalid experiment/session ID.")
    pre = await run_preflight()
    if not pre["ok"]:
        raise HTTPException(status_code=409, detail={"message": "Preflight is not ready.", "preflight": pre})
    return controller.start(body.experiment_id, body.session_id)


@app.post("/api/session/stop")
def stop_session(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not _authorized(authorization):
        raise HTTPException(status_code=401, detail="Field console token is missing or invalid.")
    return controller.stop()


@app.on_event("shutdown")
def shutdown_event() -> None:
    try:
        controller.stop()
    except Exception:
        pass
    ANNOUNCER.stop()


def main() -> None:
    parser = __import__("argparse").ArgumentParser(description="RobotCore local field session console")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not CONSOLE_TOKEN:
        raise SystemExit("ROBOTCORE_FIELD_CONTROL_TOKEN is required. Install with install_field_console.sh.")
    print("=" * 70, flush=True)
    print("RobotCore Field Console · local network only", flush=True)
    print(f"[FIELD] Open http://<PI-IP>:{args.port}/field-console on a phone on the same LAN.", flush=True)
    print("[FIELD] Read-only preflight/status are available on the LAN; start/stop require the token.", flush=True)
    print("[FIELD] Do not port-forward this service to the public internet.", flush=True)
    print(f"[FIELD] Mission directory: {MISSIONS_PATH}", flush=True)
    print("=" * 70, flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
