from __future__ import annotations

import argparse
import asyncio
import hmac
import ipaddress
import json
import time
import sys
import os
import re
import secrets
import socket
import threading
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from pairing_protocol import load_pairing_key
from receiver import ReceiverWorker, select_receiver_port, list_ports_text

RADIO_DEFAULTS = {
    "frequency_mhz": 865,
    "spreading_factor": 7,
    "bandwidth_khz": 125,
    "tx_preamble": 12,
    "rx_preamble": 15,
    "power_dbm": 14,
}
LAN_ORIGIN_REGEX = r"^http://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2[0-9]|3[01])(?:\.\d{1,3}){2}|[A-Za-z0-9.-]+\.local)(?::\d+)?$"
FIELD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,79}$")


class FieldSessionRequest(BaseModel):
    experiment_id: str = Field(min_length=3, max_length=80)
    session_id: str = Field(min_length=3, max_length=80)


def _is_lan_origin(origin: str) -> bool:
    try:
        parsed = urlsplit(origin)
        if parsed.scheme != "http" or not parsed.hostname:
            return False
        host = parsed.hostname.lower()
        if host == "localhost" or host.endswith(".local"):
            return True
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        return False


def _authorized(header: str | None, token: str) -> bool:
    value = (header or "").strip()
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    return bool(value) and hmac.compare_digest(value, token)


def _lan_ipv4_addresses() -> list[str]:
    found = set()
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            address = item[4][0]
            if not ipaddress.ip_address(address).is_loopback and not ipaddress.ip_address(address).is_link_local:
                found.add(address)
    except Exception:
        pass
    return sorted(found)


def create_app(
    port: str,
    log_dir: str,
    token: str,
    allowed_origins: set[str],
    radio: dict | None = None,
    experiment_id: str = "UNLABELLED",
    managed_sessions: bool = False,
    allow_lan_origins: bool = False,
    auto_detect_port: bool = False,
    pairing_key: bytes | None = None,
    dashboard_dir: str | None = None,
) -> FastAPI:
    radio_config = dict(RADIO_DEFAULTS)
    if radio:
        radio_config.update(radio)
    clients: set[WebSocket] = set()
    clients_lock = asyncio.Lock()
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
    worker_holder: dict[str, ReceiverWorker] = {}
    last_record: dict[str, Any] = {}
    pairing_state: dict[str, Any] = {"descriptor": None, "received_at": None}
    pi_status_state: dict[str, Any] = {"status": None, "received_at": None}
    pairing_lock = threading.RLock()

    async def broadcast(message: dict) -> None:
        async with clients_lock:
            sockets = list(clients)
        if not sockets:
            return
        failed = []
        for ws in sockets:
            try:
                await ws.send_json(message)
            except Exception:
                failed.append(ws)
        if failed:
            async with clients_lock:
                for ws in failed:
                    clients.discard(ws)

    def packet_callback(record: dict) -> None:
        last_record.clear()
        last_record.update(record)
        loop = loop_holder.get("loop")
        if loop and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(broadcast({"type": "telemetry", "record": dict(record)}), loop)
            except RuntimeError:
                pass

    def pairing_callback(descriptor: dict) -> None:
        with pairing_lock:
            pairing_state["descriptor"] = dict(descriptor)
            pairing_state["received_at"] = time.time()

    def pi_status_callback(status: dict) -> None:
        with pairing_lock:
            pi_status_state["status"] = dict(status)
            pi_status_state["received_at"] = time.time()

    def status_callback() -> None:
        loop = loop_holder.get("loop")
        if loop and not loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(broadcast_status(), loop)
            except RuntimeError:
                pass

    def get_status() -> dict:
        worker = worker_holder.get("worker")
        status = worker.status() if worker else {
            "serial_connected": False, "radio_configured": False, "serial_port": port,
            "last_error": "receiver worker not started", "rx_session_id": None,
            "experiment_id": experiment_id,
            "packets_received": 0, "packets_lost": 0, "packets_corrupt": 0, "pdr": None,
        }
        status.update({
            "read_only": True,
            "session_control_api": True,
            "managed_sessions": managed_sessions,
            "pairing_key_configured": pairing_key is not None,
            "pairing": {
                "received": bool(pairing_state["descriptor"]),
                "device_id": pairing_state["descriptor"].get("device_id") if pairing_state["descriptor"] else None,
                "last_seen_at": pairing_state["received_at"],
            },
            "pi_status_beacon": {
                "status": dict(pi_status_state["status"] or {}),
                "last_seen_at": pi_status_state["received_at"],
                "stale": not pi_status_state["received_at"] or time.time() - pi_status_state["received_at"] > 30,
            },
            "radio_config": radio_config,
        })
        return status

    async def broadcast_status() -> None:
        await broadcast({"type": "status", "data": get_status()})

    async def status_loop() -> None:
        while True:
            await broadcast_status()
            await asyncio.sleep(2.0)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop_holder["loop"] = asyncio.get_running_loop()
        worker = ReceiverWorker(
            port=port, log_dir=log_dir, radio=radio_config,
            on_packet=packet_callback, on_status=status_callback,
            experiment_id=experiment_id,
            managed_sessions=managed_sessions,
            auto_detect_port=auto_detect_port,
            on_pairing=pairing_callback,
            on_pi_status=pi_status_callback,
            pairing_key=pairing_key,
        )
        worker_holder["worker"] = worker
        worker.start()
        status_task = asyncio.create_task(status_loop())
        print(f"[BRIDGE] Receiver CSV: {Path(log_dir).resolve()}", flush=True)
        try:
            yield
        finally:
            status_task.cancel()
            try:
                await status_task
            except asyncio.CancelledError:
                pass
            worker.stop()
            if worker.is_alive():
                await asyncio.to_thread(worker.join, 3.0)

    app = FastAPI(
        title="RobotCore Field Bridge",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(allowed_origins),
        allow_origin_regex=LAN_ORIGIN_REGEX if allow_lan_origins else None,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-RobotCore-Token"],
        allow_credentials=False,
    )

    def require_control_token(authorization: str | None, x_robotcore_token: str | None = None) -> None:
        supplied = authorization or x_robotcore_token
        if not _authorized(supplied, token):
            raise HTTPException(status_code=401, detail="Invalid laptop bridge token.")

    @app.get("/api/status")
    def api_status(
        authorization: str | None = Header(default=None),
        x_robotcore_token: str | None = Header(default=None),
    ) -> dict:
        require_control_token(authorization, x_robotcore_token)
        return get_status()

    @app.post("/api/session/start")
    def start_field_session(
        body: FieldSessionRequest,
        authorization: str | None = Header(default=None),
        x_robotcore_token: str | None = Header(default=None),
    ) -> dict:
        require_control_token(authorization, x_robotcore_token)
        if not FIELD_ID_RE.fullmatch(body.experiment_id) or not FIELD_ID_RE.fullmatch(body.session_id):
            raise HTTPException(status_code=422, detail="Invalid experiment/session ID.")
        worker = worker_holder.get("worker")
        if worker is None:
            raise HTTPException(status_code=503, detail="Receiver worker is not running.")
        status = worker.status()
        if not status.get("serial_connected") or not status.get("radio_configured"):
            raise HTTPException(status_code=409, detail={
                "message": "Laptop receiver is not ready; check serial and radio configuration.",
                "status": status,
            })
        try:
            return worker.begin_field_session(body.experiment_id, body.session_id)
        except (RuntimeError, FileExistsError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/api/session/stop")
    def stop_field_session(
        body: dict | None = Body(default=None),
        authorization: str | None = Header(default=None),
        x_robotcore_token: str | None = Header(default=None),
    ) -> dict:
        require_control_token(authorization, x_robotcore_token)
        worker = worker_holder.get("worker")
        if worker is None:
            raise HTTPException(status_code=503, detail="Receiver worker is not running.")
        status = worker.status()
        requested = (body or {}).get("session_id")
        if requested and status.get("field_session_id") and requested != status.get("field_session_id"):
            raise HTTPException(status_code=409, detail="Requested session does not match the active receiver session.")
        return worker.end_field_session()

    @app.get("/api/session/files")
    def session_files(
        authorization: str | None = Header(default=None),
        x_robotcore_token: str | None = Header(default=None),
    ) -> dict:
        require_control_token(authorization, x_robotcore_token)
        worker = worker_holder.get("worker")
        if worker is None:
            raise HTTPException(status_code=503, detail="Receiver worker is not running.")
        status = worker.status()
        if status.get("capture_active"):
            raise HTTPException(status_code=409, detail="Stop the laptop receiver capture before syncing its CSV.")
        path = worker.log_path
        if not status.get("field_session_id") or path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="No completed receiver CSV is available.")
        return {
            "session_id": status["field_session_id"],
            "experiment_id": status.get("experiment_id"),
            "files": [{
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "kind": "receiver",
                "download": "/api/session/files/" + path.name,
            }],
        }

    @app.get("/api/session/files/{filename}")
    def download_session_file(
        filename: str,
        authorization: str | None = Header(default=None),
        x_robotcore_token: str | None = Header(default=None),
    ) -> FileResponse:
        require_control_token(authorization, x_robotcore_token)
        worker = worker_holder.get("worker")
        if worker is None:
            raise HTTPException(status_code=503, detail="Receiver worker is not running.")
        status = worker.status()
        path = worker.log_path
        if status.get("capture_active"):
            raise HTTPException(status_code=409, detail="Stop the laptop receiver capture before downloading its CSV.")
        if (
            not status.get("field_session_id")
            or path is None
            or Path(filename).name != filename
            or filename != path.name
            or not path.is_file()
        ):
            raise HTTPException(status_code=404, detail="Receiver session file not found.")
        return FileResponse(path, media_type="text/csv", filename=path.name)

    @app.get("/api/pairing")
    def api_pairing(
        authorization: str | None = Header(default=None),
        x_robotcore_token: str | None = Header(default=None),
    ) -> dict:
        require_control_token(authorization, x_robotcore_token)
        with pairing_lock:
            descriptor = dict(pairing_state["descriptor"] or {})
            received_at = pairing_state["received_at"]
        pi_status = dict(pi_status_state["status"] or {})
        pi_status_seen = pi_status_state["received_at"]
        visible_pi_status = {
            "status": pi_status,
            "last_seen_at": pi_status_seen,
            "stale": not pi_status_seen or time.time() - pi_status_seen > 30,
        }
        if not descriptor or received_at is None:
            return {
                "paired": False,
                "reason": "waiting_for_encrypted_lora_beacon",
                "pi_status": visible_pi_status,
            }
        now = time.time()
        valid_until = float(descriptor.get("valid_until", 0))
        worker = worker_holder.get("worker")
        receiver_status = worker.status() if worker else {}
        capture_active = bool(receiver_status.get("capture_active"))
        beacon_fresh = now - received_at <= 45 and valid_until > now
        # The Pi radio is intentionally paused from beaconing while runner.py owns the
        # transmitter. Keep the last encrypted pairing credentials available to Stop
        # while the receiver CSV proves that this exact paired session is active.
        if not beacon_fresh and not capture_active:
            return {
                "paired": False,
                "reason": "pairing_beacon_stale",
                "device_id": descriptor.get("device_id"),
                "last_seen_at": received_at,
                "capture_active": False,
                "pi_status": visible_pi_status,
            }
        return {
            "paired": True,
            "beacon_fresh": beacon_fresh,
            "capture_active": capture_active,
            "tunnel_url": descriptor["tunnel_url"],
            "control_token": descriptor["control_token"],
            "device_id": descriptor["device_id"],
            "issued_at": descriptor["issued_at"],
            "valid_until": descriptor["valid_until"],
            "last_seen_at": received_at,
            "pi_status": visible_pi_status,
        }

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def local_dashboard() -> HTMLResponse:
        directory = Path(dashboard_dir).resolve() if dashboard_dir else Path(__file__).resolve().parents[2] / "apps" / "web-dashboard"
        index = directory / "index.html"
        if not index.is_file():
            return HTMLResponse("<h1>RobotCore local dashboard files were not found.</h1>", status_code=503)
        html = index.read_text(encoding="utf-8")
        bootstrap = "<script>window.ROBOTCORE_FIELD_BOOTSTRAP=" + json.dumps(
            {"bridgeToken": token}, separators=(",", ":")
        ) + ";</script>"
        return HTMLResponse(html.replace("</head>", bootstrap + "</head>", 1))

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        origin = (ws.headers.get("origin") or "").rstrip("/")
        if origin not in allowed_origins and not (allow_lan_origins and _is_lan_origin(origin)):
            await ws.close(code=4403, reason="Origin not allowed")
            return
        await ws.accept()
        authenticated = False
        try:
            try:
                first = await asyncio.wait_for(ws.receive_json(), timeout=6.0)
            except asyncio.TimeoutError:
                await ws.close(code=4408, reason="Authentication timeout")
                return
            supplied = first.get("token", "") if isinstance(first, dict) and first.get("type") == "auth" else ""
            if not isinstance(supplied, str) or not hmac.compare_digest(supplied, token):
                await ws.close(code=4401, reason="Invalid bridge token")
                return

            authenticated = True
            async with clients_lock:
                clients.add(ws)
            await ws.send_json({"type": "auth_ok", "read_only": True, "session_control_api": True})
            await ws.send_json({"type": "status", "data": get_status()})

            # Keep the authenticated connection alive and answer browser pings.
            while True:
                message = await ws.receive_text()
                if message == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        except Exception as error:
            print(f"[BRIDGE] WebSocket client error: {error}", flush=True)
        finally:
            if authenticated:
                async with clients_lock:
                    clients.discard(ws)

    static_directory = Path(dashboard_dir).resolve() if dashboard_dir else Path(__file__).resolve().parents[2] / "apps" / "web-dashboard"
    if static_directory.is_dir():
        app.mount("/", StaticFiles(directory=str(static_directory), html=True), name="dashboard-assets")
    return app


def parse_args():
    parser = argparse.ArgumentParser(description="Authenticated read-only RobotCore laptop receiver bridge")
    parser.add_argument("--port", help="LoRa-E5 RX serial port, e.g. COM8; default from ROBOTCORE_RX_PORT or known USB ID")
    parser.add_argument("--host", default="127.0.0.1", help="bind address; use 0.0.0.0 only for an authenticated private-LAN setup")
    parser.add_argument("--managed-sessions", action="store_true", help="only write receiver CSV while a field session is active; start/stop via authenticated API")
    parser.add_argument("--allow-lan-origins", action="store_true", help="allow HTTP origins on private LAN IPs for the local Pi-served console")
    parser.add_argument("--pairing-key-file", default=os.getenv("ROBOTCORE_PAIRING_KEY_FILE", ""), help="shared 32-byte AES-GCM LoRa pairing key file")
    parser.add_argument("--dashboard-dir", default=os.getenv("ROBOTCORE_DASHBOARD_DIR", ""), help="dashboard static assets to serve from the local field station")
    parser.add_argument("--listen-port", type=int, default=8765)
    parser.add_argument("--logs", default=os.getenv("ROBOTCORE_RX_LOG_DIR", "logs"))
    parser.add_argument("--experiment-id", default=os.getenv("ROBOTCORE_EXPERIMENT_ID", "UNLABELLED"))
    parser.add_argument("--origin", action="append", default=[], help="allowed web origin; can be supplied more than once")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.allow_lan_origins and args.host not in {"0.0.0.0", "::"}:
        raise SystemExit("--allow-lan-origins requires --host 0.0.0.0 (or ::) so the phone can reach this laptop.")
    try:
        port = select_receiver_port(args.port)
    except Exception as error:
        print(f"[RX] Device selection failed: {error}", flush=True)
        raise SystemExit(2)
    os.environ["ROBOTCORE_EXPERIMENT_ID"] = args.experiment_id
    token = os.getenv("ROBOTCORE_BRIDGE_TOKEN", "").strip() or secrets.token_urlsafe(32)
    pairing_key = None
    pairing_key_path = args.pairing_key_file.strip()
    if pairing_key_path:
        try:
            pairing_key = load_pairing_key(pairing_key_path)
        except Exception as error:
            print(f"[PAIR] Encrypted pairing disabled: {error}", flush=True)
    origins = set(x.rstrip("/") for x in args.origin if x.strip())
    env_origins = os.getenv("ROBOTCORE_ALLOWED_ORIGINS", "https://robotcore-telemetry.vercel.app")
    origins.update(x.strip().rstrip("/") for x in env_origins.split(",") if x.strip())
    if not origins:
        raise SystemExit("No allowed browser origin configured.")
    print("=" * 72)
    print("RobotCore laptop field receiver bridge (READ-ONLY)")
    print(f"[RX] Port: {port}")
    print(f"[RX] Experiment ID: {args.experiment_id}")
    print(f"[RX] Allowed web origins: {', '.join(sorted(origins))}")
    print(f"[RX] Local web socket: ws://127.0.0.1:{args.listen_port}/ws")
    if args.allow_lan_origins:
        for address in _lan_ipv4_addresses():
            print(f"[RX] Private-LAN API: http://{address}:{args.listen_port}/api/status")
    print(f"[RX] Bridge token (copy into the local Field Console; do not share): {token}")
    print(f"[RX] Session mode: {'dashboard-managed' if args.managed_sessions else 'legacy always-log'}")
    print(f"[PAIR] Encrypted LoRa pairing: {'enabled' if pairing_key is not None else 'not provisioned'}")
    print(f"[UI] Local dashboard: http://<LAPTOP-IP>:{args.listen_port}/")
    print("[SECURITY] Token is generated for this run and stays in memory. Session start/stop API requests require it.")
    print("[SECURITY] Stop any desktop GUI/receiver process that is using this same serial port before continuing.")
    print("=" * 72, flush=True)
    app = create_app(
        port, args.logs, token, origins,
        experiment_id=args.experiment_id,
        managed_sessions=args.managed_sessions,
        allow_lan_origins=args.allow_lan_origins,
        auto_detect_port=not args.port and not os.getenv("ROBOTCORE_RX_PORT", "").strip(),
        pairing_key=pairing_key,
        dashboard_dir=args.dashboard_dir or None,
    )
    uvicorn.run(app, host=args.host, port=args.listen_port, log_level="info" if args.allow_lan_origins else "warning", access_log=False)


if __name__ == "__main__":
    main()
