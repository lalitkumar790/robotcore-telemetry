from __future__ import annotations

import argparse
import asyncio
import hmac
import os
import secrets
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn

from receiver import ReceiverWorker, select_receiver_port, list_ports_text

RADIO_DEFAULTS = {
    "frequency_mhz": 865,
    "spreading_factor": 7,
    "bandwidth_khz": 125,
    "tx_preamble": 12,
    "rx_preamble": 15,
    "power_dbm": 14,
}


def create_app(port: str, log_dir: str, token: str, allowed_origins: set[str], radio: dict | None = None) -> FastAPI:
    radio_config = dict(RADIO_DEFAULTS)
    if radio:
        radio_config.update(radio)
    clients: set[WebSocket] = set()
    clients_lock = asyncio.Lock()
    loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
    worker_holder: dict[str, ReceiverWorker] = {}
    last_record: dict[str, Any] = {}

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
            "experiment_id": os.getenv("ROBOTCORE_EXPERIMENT_ID", "UNLABELLED"),
            "packets_received": 0, "packets_lost": 0, "packets_corrupt": 0, "pdr": None,
        }
        status.update({"read_only": True, "radio_config": radio_config})
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

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket):
        origin = (ws.headers.get("origin") or "").rstrip("/")
        if origin not in allowed_origins:
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
            await ws.send_json({"type": "auth_ok", "read_only": True})
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

    return app


def parse_args():
    parser = argparse.ArgumentParser(description="Authenticated read-only RobotCore laptop receiver bridge")
    parser.add_argument("--port", help="LoRa-E5 RX serial port, e.g. COM8; default from ROBOTCORE_RX_PORT or known USB ID")
    parser.add_argument("--host", default="127.0.0.1", help="bind address; keep loopback when using cloudflared (default 127.0.0.1)")
    parser.add_argument("--listen-port", type=int, default=8765)
    parser.add_argument("--logs", default=os.getenv("ROBOTCORE_RX_LOG_DIR", "logs"))
    parser.add_argument("--experiment-id", default=os.getenv("ROBOTCORE_EXPERIMENT_ID", "UNLABELLED"))
    parser.add_argument("--origin", action="append", default=[], help="allowed web origin; can be supplied more than once")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        port = select_receiver_port(args.port)
    except Exception as error:
        print(f"[RX] Device selection failed: {error}", flush=True)
        raise SystemExit(2)
    os.environ["ROBOTCORE_EXPERIMENT_ID"] = args.experiment_id
    token = os.getenv("ROBOTCORE_BRIDGE_TOKEN", "").strip() or secrets.token_urlsafe(32)
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
    print(f"[RX] Bridge token (copy into Device status on your phone; do not share): {token}")
    print("[SECURITY] Token is generated for this run and stays in memory. No telemetry API or remote write controls are exposed.")
    print("[SECURITY] Stop any desktop GUI/receiver process that is using this same serial port before continuing.")
    print("=" * 72, flush=True)
    app = create_app(port, args.logs, token, origins)
    uvicorn.run(app, host=args.host, port=args.listen_port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
