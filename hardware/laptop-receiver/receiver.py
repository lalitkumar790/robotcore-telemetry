from __future__ import annotations

import csv
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import serial
from serial.tools import list_ports

from protocol import decode_packet

GPS_VID_PID = (0x1A86, 0x7523)
LORA_VID_PID = (0x10C4, 0xEA60)
RX_META_RE = re.compile(r"RSSI:\s*(-?\d+)\s*,\s*SNR:\s*(-?\d+)", re.IGNORECASE)
EXPERIMENT_ID = os.getenv("ROBOTCORE_EXPERIMENT_ID", "").strip() or "UNLABELLED"


def list_ports_text() -> str:
    ports = list(list_ports.comports())
    if not ports:
        return "  (no USB serial devices detected)"
    return "\n".join(
        f"  {p.device} | {p.vid:04X}:{p.pid:04X}" if p.vid is not None and p.pid is not None
        else f"  {p.device} | VID/PID unknown | {p.description}"
        for p in ports
    )


def select_receiver_port(explicit: str | None = None) -> str:
    override = (explicit or os.getenv("ROBOTCORE_RX_PORT", "")).strip()
    if override:
        return override
    ports = list(list_ports.comports())
    known = [p for p in ports if (p.vid, p.pid) == LORA_VID_PID]
    if len(known) == 1:
        return known[0].device
    details = list_ports_text()
    if len(known) > 1:
        raise RuntimeError(
            "More than one LoRa-E5 USB adapter matches 10C4:EA60. Re-run with --port COMx.\nDetected devices:\n" + details
        )
    raise RuntimeError(
        "Could not identify the LoRa-E5 receiver by its known USB ID (10C4:EA60). "
        "Do not guess or open a GPS port by accident. Re-run with --port COMx after checking Device Manager.\n"
        "Detected devices:\n" + details
    )


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ReceiverWorker(threading.Thread):
    """Single owner of the laptop receiver serial port, CSV log and packet stream."""

    def __init__(self, port: str, log_dir: str, radio: dict, on_packet: Callable[[dict], None], on_status: Callable[[], None], experiment_id: str | None = None):
        super().__init__(daemon=True, name="RobotCoreRadioReceiver")
        self.port_name = port
        self.experiment_id = (experiment_id or EXPERIMENT_ID or "UNLABELLED").strip()
        self.log_dir = Path(log_dir).expanduser().resolve()
        self.radio = dict(radio)
        self.on_packet = on_packet
        self.on_status = on_status
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.serial_port = None
        self.serial_connected = False
        self.radio_configured = False
        self.radio_config_response = ""
        self.last_error: str | None = None
        self.last_packet_unix_ms: int | None = None
        self.last_rssi: int | None = None
        self.last_snr: int | None = None
        self.packets_received = 0
        self.packets_lost = 0
        self.packets_corrupt = 0
        self.packets_duplicate = 0
        self.packets_out_of_order = 0
        self.sequence_resets_suspected = 0
        self.last_sequence: int | None = None
        self.source_index = 0
        self.session_id = datetime.now(timezone.utc).strftime("RX-%Y%m%dT%H%M%SZ")
        self._csv_file = None
        self._csv_writer = None
        self.log_path: Path | None = None
        self._pending_rssi: int | None = None
        self._pending_snr: int | None = None

    def status(self) -> dict:
        with self.lock:
            total = self.packets_received + self.packets_lost
            return {
                "serial_connected": self.serial_connected,
                "radio_configured": self.radio_configured,
                "serial_port": self.port_name,
                "radio_config_response": self.radio_config_response[-400:],
                "last_error": self.last_error,
                "rx_session_id": self.session_id,
                "experiment_id": self.experiment_id,
                "log_file": str(self.log_path) if self.log_path else None,
                "packets_received": self.packets_received,
                "packets_lost": self.packets_lost,
                "packets_corrupt": self.packets_corrupt,
                "packets_duplicate": self.packets_duplicate,
                "packets_out_of_order": self.packets_out_of_order,
                "sequence_resets_suspected": self.sequence_resets_suspected,
                "pdr": round(100.0 * self.packets_received / total, 3) if total else None,
                "last_packet_unix_ms": self.last_packet_unix_ms,
                "last_rssi_dbm": self.last_rssi,
                "last_snr_db": self.last_snr,
            }

    def _status_changed(self) -> None:
        try:
            self.on_status()
        except Exception:
            pass

    def _command(self, command: str, timeout_s: float = 1.5, stop_markers: tuple[str, ...] = ("OK",)) -> str:
        port = self.serial_port
        if port is None or not port.is_open:
            raise RuntimeError("serial port is not open")
        port.reset_input_buffer()
        port.write((command + "\r\n").encode("ascii"))
        port.flush()
        deadline = time.monotonic() + timeout_s
        lines = []
        while time.monotonic() < deadline:
            raw = port.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                continue
            lines.append(line)
            upper = line.upper()
            if any(m.upper() in upper for m in stop_markers) or "ERROR" in upper or "FAIL" in upper:
                break
        return "\n".join(lines).strip()

    def _configure_radio(self) -> None:
        mode_response = self._command("AT+MODE=TEST", timeout_s=1.5, stop_markers=("+TEST", "OK"))
        c = self.radio
        command = (
            f"AT+TEST=RFCFG,{c['frequency_mhz']},SF{c['spreading_factor']},"
            f"{c['bandwidth_khz']},{c['tx_preamble']},{c['rx_preamble']},{c['power_dbm']},ON,OFF,OFF"
        )
        response = self._command(command, timeout_s=1.8, stop_markers=("+TEST: RFCFG", "OK"))
        upper = response.upper()
        confirmed = bool(response) and ("+TEST: RFCFG" in upper or "\nOK" in upper or upper.strip() == "OK")
        if "ERROR" in upper or "FAIL" in upper:
            confirmed = False
        with self.lock:
            self.radio_configured = confirmed
            self.radio_config_response = (mode_response + "\n" + response).strip()
        rx_response = self._command("AT+TEST=RXLRPKT", timeout_s=1.0, stop_markers=("+TEST: RXLRPKT", "OK"))
        with self.lock:
            self.serial_connected = True
            self.last_error = None if self.serial_port and self.serial_port.is_open else "serial port closed"
            if rx_response and ("ERROR" in rx_response.upper() or "FAIL" in rx_response.upper()):
                self.last_error = "Could not place LoRa-E5 in RX mode: " + rx_response[-300:]
        self._status_changed()

    def _prepare_log(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = self.log_dir / f"receiver_{stamp}.csv"
        self._csv_file = self.log_path.open("w", newline="", encoding="utf-8")
        fields = [
            "RX Time UTC", "RX Epoch ms", "Experiment ID", "RX Session ID",
            "Sequence", "Protocol", "Latitude", "Longitude", "Speed (km/h)",
            "RSSI (dBm)", "SNR (dB)", "Lost Before", "Out Of Order",
            "CRC Valid", "Packets Received", "Packets Lost", "Packets Corrupt",
            "PDR (%)", "IMU Fields Present", "IMU Health",
            "Roll (deg)", "Pitch (deg)", "Yaw (deg)",
            "AccelX (g)", "AccelY (g)", "AccelZ (g)",
            "GyroX (deg/s)", "GyroY (deg/s)", "GyroZ (deg/s)",
        ]
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=fields, extrasaction="ignore")
        self._csv_writer.writeheader()
        self._csv_file.flush()

    def _record_sequence(self, sequence: int) -> tuple[int, bool, bool]:
        with self.lock:
            previous = self.last_sequence
            if previous is None:
                self.last_sequence = sequence
                return 0, False, False
            delta = (sequence - previous) % 65535  # firmware sequence cycles 1..65535, then back to 1
            if delta == 0:
                self.packets_duplicate += 1
                return 0, False, True
            if previous < 50000 and previous >= 1000 and sequence <= 10:
                # Likely transmitter restarted mid-receiver-session. Do not invent thousands of lost packets.
                self.sequence_resets_suspected += 1
                self.last_sequence = sequence
                return 0, False, False
            if delta > 32767:
                self.packets_out_of_order += 1
                return 0, True, False
            lost_before = max(0, delta - 1)
            self.packets_lost += lost_before
            self.last_sequence = sequence
            return lost_before, False, False

    def _process_packet(self, payload: bytes) -> None:
        now_ms = int(time.time() * 1000)
        # RSSI/SNR are emitted on the metadata line immediately before the payload.
        # Consume them exactly once so a malformed/absent metadata line cannot reuse stale values.
        rssi, snr = self._pending_rssi, self._pending_snr
        self._pending_rssi, self._pending_snr = None, None
        try:
            record = decode_packet(payload)
        except ValueError as error:
            with self.lock:
                self.packets_corrupt += 1
                self.last_error = "Rejected packet: " + str(error)
            self._status_changed()
            return

        lost_before, out_of_order, duplicate = self._record_sequence(record["sequence"])
        if duplicate:
            self._status_changed()
            return
        with self.lock:
            self.packets_received += 1
            self.source_index += 1
            source_index = self.source_index
            self.last_packet_unix_ms = now_ms
            self.last_rssi = self._pending_rssi
            self.last_snr = self._pending_snr
            self.last_error = None
            received_count = self.packets_received
            lost_count = self.packets_lost
            corrupt_count = self.packets_corrupt
            total = received_count + lost_count
            pdr = 100.0 * received_count / total if total else None

        received = dict(record)
        received.update({
            "receivedAt": now_ms,
            "receivedAtUtc": utc_iso(),
            "sourceIndex": source_index,
            "source": "laptop-rx",
            "rssi": rssi,
            "snr": snr,
            "lostBefore": lost_before,
            "outOfOrder": out_of_order,
            "inOrder": not out_of_order and lost_before == 0,
            "packetsReceived": received_count,
            "packetsLost": lost_count,
            "packetsCorrupt": corrupt_count,
            "pdr": pdr,
            "rxSessionId": self.session_id,
            "experimentId": self.experiment_id,
        })
        if self._csv_writer is not None:
            row = {
                "RX Time UTC": received["receivedAtUtc"], "RX Epoch ms": now_ms,
                "Experiment ID": self.experiment_id, "RX Session ID": self.session_id,
                "Sequence": record["sequence"], "Protocol": record["protocol"],
                "Latitude": record["latitude"], "Longitude": record["longitude"],
                "Speed (km/h)": record["speed"], "RSSI (dBm)": rssi if rssi is not None else "",
                "SNR (dB)": snr if snr is not None else "",
                "Lost Before": lost_before, "Out Of Order": int(out_of_order), "CRC Valid": 1,
                "Packets Received": received_count, "Packets Lost": lost_count, "Packets Corrupt": corrupt_count,
                "PDR (%)": round(pdr, 3) if pdr is not None else "",
                "IMU Fields Present": int(bool(record["imuPresent"])), "IMU Health": record.get("imu_health", ""),
                "Roll (deg)": record["roll"] if record["roll"] is not None else "",
                "Pitch (deg)": record["pitch"] if record["pitch"] is not None else "",
                "Yaw (deg)": record["yaw"] if record["yaw"] is not None else "",
                "AccelX (g)": record["ax"] if record["ax"] is not None else "",
                "AccelY (g)": record["ay"] if record["ay"] is not None else "",
                "AccelZ (g)": record["az"] if record["az"] is not None else "",
                "GyroX (deg/s)": record["gx"] if record["gx"] is not None else "",
                "GyroY (deg/s)": record["gy"] if record["gy"] is not None else "",
                "GyroZ (deg/s)": record["gz"] if record["gz"] is not None else "",
            }
            self._csv_writer.writerow(row)
            self._csv_file.flush()
        try:
            self.on_packet(received)
        except Exception as error:
            with self.lock:
                self.last_error = f"Telemetry broadcast error: {error}"
        self._status_changed()

    def run(self) -> None:
        self._prepare_log()
        try:
            self.serial_port = serial.Serial(self.port_name, baudrate=9600, timeout=0.25, write_timeout=2.0)
            with self.lock:
                self.serial_connected = True
                self.last_error = None
            self._status_changed()
            self._configure_radio()
            pending_buffer = ""
            while not self.stop_event.is_set():
                raw = self.serial_port.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="ignore").strip()
                if not line:
                    continue
                match = RX_META_RE.search(line)
                if match:
                    self._pending_rssi = int(match.group(1))
                    self._pending_snr = int(match.group(2))
                    continue
                if "RX" in line.upper() and '"' in line:
                    try:
                        hex_payload = line.split('"', 2)[1].strip()
                        payload = bytes.fromhex(hex_payload)
                    except (IndexError, ValueError):
                        with self.lock:
                            self.packets_corrupt += 1
                            self.last_error = "Malformed LoRa-E5 RX payload line"
                        self._status_changed()
                        continue
                    self._process_packet(payload)
        except Exception as error:
            with self.lock:
                self.last_error = f"{type(error).__name__}: {error}"
                self.serial_connected = False
            print("[RX] Fatal receiver error:", self.last_error, flush=True)
            self._status_changed()
        finally:
            with self.lock:
                self.serial_connected = False
            try:
                if self.serial_port is not None:
                    self.serial_port.close()
            except Exception:
                pass
            try:
                if self._csv_file is not None:
                    self._csv_file.flush()
                    self._csv_file.close()
            except Exception:
                pass
            self._status_changed()

    def stop(self) -> None:
        self.stop_event.set()
        try:
            if self.serial_port is not None and self.serial_port.is_open:
                self.serial_port.cancel_read()
        except Exception:
            pass
        self.join(timeout=3.0)
