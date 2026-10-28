from __future__ import annotations

import os
from dataclasses import dataclass

from serial.tools import list_ports

from config import GPS_VID_PID, LORA_VID_PID


@dataclass(frozen=True)
class SerialCandidate:
    device: str
    description: str
    manufacturer: str
    vid: int | None
    pid: int | None
    serial_number: str | None
    hwid: str

    @classmethod
    def from_port(cls, port) -> "SerialCandidate":
        return cls(
            device=port.device,
            description=port.description or "",
            manufacturer=port.manufacturer or "",
            vid=port.vid,
            pid=port.pid,
            serial_number=port.serial_number,
            hwid=port.hwid or "",
        )

    def describe(self) -> str:
        usb_id = f"{self.vid:04X}:{self.pid:04X}" if self.vid is not None and self.pid is not None else "VID/PID unknown"
        return f"{self.device} | {usb_id} | {self.description} | {self.manufacturer} | {self.hwid}"


def serial_candidates() -> list[SerialCandidate]:
    return [SerialCandidate.from_port(port) for port in list_ports.comports()]


def print_serial_candidates() -> None:
    candidates = serial_candidates()
    if not candidates:
        print("No USB serial devices detected. Check cables, USB power, permissions and dmesg.")
        return
    print("Detected serial devices:")
    for candidate in candidates:
        print("  " + candidate.describe())


def select_serial_port(role: str, exclude: set[str] | None = None) -> str:
    if role not in {"gps", "lora"}:
        raise ValueError(f"Unknown serial role: {role}")
    override_name = "ROBOTCORE_GPS_PORT" if role == "gps" else "ROBOTCORE_LORA_PORT"
    override = os.getenv(override_name, "").strip()
    excluded = exclude or set()
    candidates = [p for p in serial_candidates() if p.device not in excluded]
    if override:
        if override in excluded:
            raise RuntimeError(f"{override_name} points to {override}, already selected for another device.")
        return override

    vid_pid = GPS_VID_PID if role == "gps" else LORA_VID_PID
    known = [p for p in candidates if (p.vid, p.pid) == vid_pid]
    if len(known) == 1:
        return known[0].device
    if len(known) > 1:
        matches = known
        reason = f"multiple known {role.upper()} USB adapters"
    else:
        hints = ("gps", "gnss", "ublox", "u-blox") if role == "gps" else ("lora-e5", "lorawan")
        matches = [p for p in candidates if any(h in (p.description + " " + p.manufacturer).lower() for h in hints)]
        reason = f"no known VID/PID for {role.upper()} and description matching is ambiguous/unavailable"

    if len(matches) == 1:
        return matches[0].device

    detail = "\n".join("  " + p.describe() for p in candidates) or "  (none)"
    raise RuntimeError(
        f"Could not safely identify the {role.upper()} port: {reason}.\n"
        f"Detected ports:\n{detail}\n"
        f"Set {override_name} to the correct device path and retry."
    )


if __name__ == "__main__":
    print_serial_candidates()
