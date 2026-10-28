from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Optional

from bleak import BleakClient, BleakScanner
from config import IMU_ADDRESS, IMU_NAME_HINT

SERVICE_UUID = "0000ffe5-0000-1000-8000-00805f9a34fb"
NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9a34fb"


@dataclass(frozen=True)
class IMUReading:
    ax: float
    ay: float
    az: float
    gx: float
    gy: float
    gz: float
    roll: float
    pitch: float
    yaw: float


class WitMotion:
    """WT901BLE68 client with retry, freshness checks, and observable connection errors."""

    def __init__(self, address: str | None = None, name_hint: str | None = None, stale_after_s: float = 3.5):
        self.address = (address or IMU_ADDRESS or "").strip()
        self.name_hint = (name_hint or IMU_NAME_HINT or "WT901BLE68").casefold()
        self.stale_after_s = stale_after_s
        self._lock = threading.Lock()
        self._latest: Optional[IMUReading] = None
        self._last_sample_monotonic: float | None = None
        self._connected = False
        self._running = True
        self._client: BleakClient | None = None
        self.last_error: str | None = None
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="WitMotionBLE", daemon=True)
        self._thread.start()
        self._future = asyncio.run_coroutine_threadsafe(self._reconnect_loop(), self._loop)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _find_device(self):
        devices = await BleakScanner.discover(timeout=7.0, return_adv=True)
        wanted = self.address.replace(":", "").replace("-", "").casefold()
        found = []
        for _key, item in devices.items():
            device, advertisement = item
            address = (getattr(device, "address", "") or "").replace(":", "").replace("-", "").casefold()
            name = (getattr(device, "name", None) or getattr(advertisement, "local_name", None) or "").casefold()
            if (wanted and address == wanted) or (self.name_hint and self.name_hint in name) or "wt901" in name or "witmotion" in name:
                found.append((device, name, address))
        if not found:
            return None
        if self.address:
            # An explicit address is a pin, not a hint: never silently switch to
            # a different nearby BLE sensor if the requested device is absent.
            exact = [item for item in found if item[2] == wanted]
            if exact:
                return exact[0][0]
            return None
        return found[0][0]

    async def _reconnect_loop(self) -> None:
        while self._running:
            client = None
            try:
                device = await self._find_device()
                if device is None:
                    self.last_error = "IMU not found by address/name; retrying scan in 3 seconds"
                    await asyncio.sleep(3.0)
                    continue
                client = BleakClient(device, timeout=10.0)
                self._client = client
                await client.connect()
                await client.start_notify(NOTIFY_UUID, self._notification_handler)
                with self._lock:
                    self._connected = True
                self.last_error = None
                print(f"[IMU] Connected to {device.name or device.address}; notifications on FFE4")
                while self._running and client.is_connected:
                    await asyncio.sleep(0.25)
                raise ConnectionError("BLE disconnected")
            except asyncio.CancelledError:
                break
            except Exception as error:
                self.last_error = f"{type(error).__name__}: {error}"
                print(f"[IMU] {self.last_error}; retrying in 3 seconds")
            finally:
                with self._lock:
                    self._connected = False
                if client is not None:
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
                if self._client is client:
                    self._client = None
            if self._running:
                await asyncio.sleep(3.0)

    @staticmethod
    def decode(packet: bytes) -> Optional[IMUReading]:
        if len(packet) != 20 or packet[0] != 0x55 or packet[1] != 0x61:
            return None
        values = [int.from_bytes(packet[i:i + 2], "little", signed=True) for i in range(2, 20, 2)]
        ax, ay, az, gx, gy, gz, roll, pitch, yaw = values
        return IMUReading(
            ax=ax / 32768.0 * 16.0, ay=ay / 32768.0 * 16.0, az=az / 32768.0 * 16.0,
            gx=gx / 32768.0 * 2000.0, gy=gy / 32768.0 * 2000.0, gz=gz / 32768.0 * 2000.0,
            roll=roll / 32768.0 * 180.0, pitch=pitch / 32768.0 * 180.0, yaw=yaw / 32768.0 * 180.0,
        )

    def _notification_handler(self, _sender, data: bytearray) -> None:
        reading = self.decode(bytes(data))
        if reading is None:
            return
        with self._lock:
            self._latest = reading
            self._last_sample_monotonic = time.monotonic()

    def get_reading(self) -> tuple[Optional[IMUReading], bool, Optional[float], Optional[str]]:
        with self._lock:
            latest, connected, sample_at = self._latest, self._connected, self._last_sample_monotonic
        age = time.monotonic() - sample_at if sample_at is not None else None
        fresh = connected and age is not None and age <= self.stale_after_s
        return (latest if fresh else None), fresh, age, self.last_error

    def close(self) -> None:
        self._running = False
        if self._client is not None and self._client.is_connected:
            try:
                future = asyncio.run_coroutine_threadsafe(self._client.disconnect(), self._loop)
                future.result(timeout=3.0)
            except Exception:
                pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except RuntimeError:
            pass
        self._thread.join(timeout=3.0)
