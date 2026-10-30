from __future__ import annotations

import csv
import os
import re
import threading
import time
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import serial
from serial.tools import list_ports

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from pairing_protocol import (
    PairingError, decode_pairing_beacon, decode_status_beacon,
    is_pairing_beacon, is_status_beacon,
)
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

    def __init__(self, port: str, log_dir: str, radio: dict, on_packet: Callable[[dict], None], on_status: Callable[[], None], experiment_id: str | None = None, managed_sessions: bool = False, auto_detect_port: bool = False, on_pairing: Callable[[dict], None] | None = None, on_pi_status: Callable[[dict], None] | None = None, pairing_key: bytes | None = None):
        super().__init__(daemon=True, name="RobotCoreRadioReceiver")
        self.port_name = port
        self.experiment_id = (experiment_id or EXPERIMENT_ID or "UNLABELLED").strip()
        self.managed_sessions = managed_sessions
        self.auto_detect_port = auto_detect_port
        self.on_pairing = on_pairing
        self.on_pi_status = on_pi_status
        self.pairing_key = pairing_key
        self.capture_active = not managed_sessions
        self.field_session_id: str | None = None
        self.log_dir = Path(log_dir).expanduser().resolve()
        self.radio = dict(radio)
        self.on_packet = on_packet
        self.on_status = on_status
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.serial_port = None
        self.serial_connected = False
        self.radio_configured = False
        self.radio_config_response = ""
        self.last_error: str | None = None
        self.last_packet_unix_ms: int | None = None
        self.last_rssi: int | None = None
        self.last_snr: int | None = None
        self.pairing_received = 0
        self.pairing_rejected = 0
        self.last_pairing_unix_ms: int | None = None
        self.last_pairing_device_id: str | None = None
        self.last_pairing_error: str | None = None
        self.pi_status_received = 0
        self.pi_status_rejected = 0
        self.last_pi_status_unix_ms: int | None = None
        self.last_pi_status: dict | None = None
        self.last_pi_status_error: str | None = None
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
                "field_session_id": self.field_session_id,
                "capture_active": self.capture_active,
                "last_packet_age_s": max(0.0, time.time() - self.last_packet_unix_ms / 1000.0) if self.last_packet_unix_ms else None,
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
                "pairing_key_configured": self.pairing_key is not None,
                "pairing_received": self.pairing_received,
                "pairing_rejected": self.pairing_rejected,
                "last_pairing_unix_ms": self.last_pairing_unix_ms,
                "last_pairing_device_id": self.last_pairing_device_id,
                "last_pairing_error": self.last_pairing_error,
                "pi_status_received": self.pi_status_received,
                "pi_status_rejected": self.pi_status_rejected,
                "last_pi_status_unix_ms": self.last_pi_status_unix_ms,
                "last_pi_status": dict(self.last_pi_status) if self.last_pi_status else None,
                "last_pi_status_error": self.last_pi_status_error,
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
        if self._csv_file is not None:
            try:
                self._csv_file.flush()
                self._csv_file.close()
            except Exception:
                pass
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = lambda value: re.sub(r"[^A-Za-z0-9._-]+", "-", value or "").strip("._-")[:80] or "session"
        if self.field_session_id:
            self.log_path = self.log_dir / f"receiver_{safe(self.experiment_id)}_{safe(self.field_session_id)}.csv"
        else:
            self.log_path = self.log_dir / f"receiver_{stamp}.csv"
        if self.log_path.exists():
            # A session ID is a unique run identifier; never append into an older file with the same name.
            raise FileExistsError(f"Receiver log already exists for this session: {self.log_path.name}")
        self._csv_file = self.log_path.open("w", newline="", encoding="utf-8")
        fields = [
            "RX Time UTC", "RX Epoch ms", "Experiment ID", "RX Session ID", "Field Session ID",
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

    def begin_field_session(self, experiment_id: str, session_id: str) -> dict:
        with self.lock:
            if self.capture_active and self.field_session_id:
                raise RuntimeError(f"Field session {self.field_session_id} is already recording.")
            self.experiment_id = experiment_id
            self.field_session_id = session_id
            self.packets_received = 0
            self.packets_lost = 0
            self.packets_corrupt = 0
            self.packets_duplicate = 0
            self.packets_out_of_order = 0
            self.sequence_resets_suspected = 0
            self.last_sequence = None
            self.source_index = 0
            self.last_packet_unix_ms = None
            self.last_rssi = None
            self.last_snr = None
            self.last_error = None
            self._pending_rssi = None
            self._pending_snr = None
            self.capture_active = False
            self._prepare_log()
            self.capture_active = True
            return self.status()

    def end_field_session(self) -> dict:
        with self.lock:
            self.capture_active = False
            if self._csv_file is not None:
                try:
                    self._csv_file.flush()
                    self._csv_file.close()
                finally:
                    self._csv_file = None
                    self._csv_writer = None
            return self.status()

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

    def _process_pairing_beacon(self, payload: bytes, rssi: int | None, snr: int | None, now_ms: int) -> None:
        if self.pairing_key is None:
            with self.lock:
                self.pairing_rejected += 1
                self.last_pairing_error = "Encrypted pairing beacon received, but laptop pairing key is not configured."
            self._status_changed()
            return
        try:
            descriptor = decode_pairing_beacon(payload, self.pairing_key)
            received = {
                **descriptor,
                "rssi_dbm": rssi,
                "snr_db": snr,
                "received_at_unix_ms": now_ms,
                "received_at_utc": utc_iso(),
            }
            with self.lock:
                self.pairing_received += 1
                self.last_pairing_unix_ms = now_ms
                self.last_pairing_device_id = descriptor["device_id"]
                self.last_pairing_error = None
            if self.on_pairing is not None:
                self.on_pairing(received)
        except PairingError as error:
            with self.lock:
                self.pairing_rejected += 1
                self.last_pairing_error = str(error)
        except Exception as error:
            with self.lock:
                self.pairing_rejected += 1
                self.last_pairing_error = f"{type(error).__name__}: {error}"
        self._status_changed()

    def _process_status_beacon(self, payload: bytes, rssi: int | None, snr: int | None, now_ms: int) -> None:
        if self.pairing_key is None:
            with self.lock:
                self.pi_status_rejected += 1
                self.last_pi_status_error = "Encrypted Pi status beacon received, but laptop pairing key is not configured."
            self._status_changed()
            return
        try:
            status = decode_status_beacon(payload, self.pairing_key)
            status.update({
                "rssi_dbm": rssi,
                "snr_db": snr,
                "received_at_unix_ms": now_ms,
                "received_at_utc": utc_iso(),
            })
            with self.lock:
                self.pi_status_received += 1
                self.last_pi_status_unix_ms = now_ms
                self.last_pi_status = dict(status)
                self.last_pi_status_error = None
            if self.on_pi_status is not None:
                self.on_pi_status(status)
        except PairingError as error:
            with self.lock:
                self.pi_status_rejected += 1
                self.last_pi_status_error = str(error)
        except Exception as error:
            with self.lock:
                self.pi_status_rejected += 1
                self.last_pi_status_error = f"{type(error).__name__}: {error}"
        self._status_changed()

    def _process_packet(self, payload: bytes) -> None:
        now_ms = int(time.time() * 1000)
        # RSSI/SNR are emitted on the metadata line immediately before the payload.
        # Consume them exactly once so a malformed/absent metadata line cannot reuse stale values.
        rssi, snr = self._pending_rssi, self._pending_snr
        self._pending_rssi, self._pending_snr = None, None
        if is_pairing_beacon(payload):
            self._process_pairing_beacon(payload, rssi, snr, now_ms)
            return
        if is_status_beacon(payload):
            self._process_status_beacon(payload, rssi, snr, now_ms)
            return
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
            self.last_rssi = rssi
            self.last_snr = snr
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
        with self.lock:
            if self._csv_writer is not None and self.capture_active:
                row = {
                    "RX Time UTC": received["receivedAtUtc"], "RX Epoch ms": now_ms,
                    "Experiment ID": self.experiment_id, "RX Session ID": self.session_id,
                    "Field Session ID": self.field_session_id or "",
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
        if not self.managed_sessions:
            self._prepare_log()
        # Keep the bridge alive and the CSV open if the USB radio is briefly
        # unplugged or Windows resets the COM port. The phone can continue
        # observing status while the receiver retries every two seconds.
        while not self.stop_event.is_set():
            try:
                if self.auto_detect_port:
                    detected_port = select_receiver_port()
                    if detected_port != self.port_name:
                        with self.lock:
                            self.port_name = detected_port
                            self.last_error = "LoRa-E5 re-detected on " + detected_port
                        self._status_changed()
                self.serial_port = serial.Serial(
                    self.port_name, baudrate=9600, timeout=0.25, write_timeout=2.0
                )
                self._pending_rssi = None
                self._pending_snr = None
                with self.lock:
                    self.serial_connected = True
                    self.radio_configured = False
                    self.last_error = None
                self._status_changed()
                self._configure_radio()
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
                    self.radio_configured = False
                if not self.stop_event.is_set():
                    print("[RX] Receiver error; retrying in 2 seconds:", self.last_error, flush=True)
                self._status_changed()
            finally:
                with self.lock:
                    self.serial_connected = False
                    self.radio_configured = False
                try:
                    if self.serial_port is not None:
                        self.serial_port.close()
                except Exception:
                    pass
                self.serial_port = None
                self._pending_rssi = None
                self._pending_snr = None
                self._status_changed()
            if not self.stop_event.is_set():
                self.stop_event.wait(2.0)

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
