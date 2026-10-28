from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

import pynmea2
import serial

from config import GPS_BAUD, GPS_READ_TIMEOUT
from device_discovery import select_serial_port


@dataclass(frozen=True)
class GPSFix:
    latitude: float
    longitude: float
    speed_kmh: float
    nmea_time: str | None
    received_at_unix: float

    def as_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "speed_kmh": self.speed_kmh,
            "nmea_time": self.nmea_time,
            "received_at_unix": self.received_at_unix,
            "received_at_utc": datetime.fromtimestamp(self.received_at_unix, timezone.utc).isoformat(),
        }


class GPS:
    def __init__(self, port: str, other_port: str | None = None):
        self.port = port
        self.other_port = other_port
        self.serial = None
        self.last_error: str | None = None
        self._last_reconnect_attempt = 0.0
        self._open(port)

    def _open(self, port: str) -> None:
        self.serial = serial.Serial(port=port, baudrate=GPS_BAUD, timeout=GPS_READ_TIMEOUT)
        self.port = port
        self.last_error = None
        print(f"[GPS] Opened {port} at {GPS_BAUD} baud")

    def read_fix(self, timeout_s: float = 1.5) -> GPSFix | None:
        deadline = time.monotonic() + max(0.05, timeout_s)
        while time.monotonic() < deadline:
            try:
                raw = self.serial.readline()
            except (serial.SerialException, OSError) as error:
                self.last_error = str(error)
                try:
                    self.serial.close()
                except Exception:
                    pass
                self.serial = None
                return None
            if not raw:
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            if not (line.startswith("$GNRMC") or line.startswith("$GPRMC")):
                continue
            try:
                msg = pynmea2.parse(line)
            except pynmea2.ParseError:
                continue
            if getattr(msg, "status", "V") != "A":
                continue
            lat, lon = float(msg.latitude), float(msg.longitude)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                continue

            # pynmea2 spd_over_grnd is knots; RTPv2 stores km/h.
            knots = float(msg.spd_over_grnd or 0.0)
            self.last_error = None
            return GPSFix(
                latitude=lat, longitude=lon, speed_kmh=max(0.0, knots * 1.852),
                nmea_time=str(msg.timestamp) if msg.timestamp else None,
                received_at_unix=time.time(),
            )
        return None

    def try_reconnect(self) -> bool:
        if self.serial is not None and self.serial.is_open:
            return True
        now = time.monotonic()
        if now - self._last_reconnect_attempt < 2.0:
            return False
        self._last_reconnect_attempt = now
        try:
            candidate = select_serial_port("gps", exclude={self.other_port} if self.other_port else set())
            self._open(candidate)
            return True
        except Exception as error:
            self.last_error = str(error)
            return False

    def close(self) -> None:
        if self.serial is not None:
            try:
                self.serial.close()
            finally:
                self.serial = None
