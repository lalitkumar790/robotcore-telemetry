from __future__ import annotations

import re
import time

import serial

from config import LORA_BAUD, RadioConfig

_ERROR = re.compile(r"\b(ERROR|FAIL|ERR)\b", re.IGNORECASE)
_RX_META = re.compile(r"RSSI:\s*(-?\d+)\s*,\s*SNR:\s*(-?\d+)", re.IGNORECASE)
_RX_PACKET = re.compile(r"\+TEST:\s*RX\s+\"?([0-9A-Fa-f ]+)\"?", re.IGNORECASE)


class LoRaE5:
    def __init__(self, port: str, config: RadioConfig):
        self.port = port
        self.config = config
        self.serial = serial.Serial(port=port, baudrate=LORA_BAUD, timeout=0.2, write_timeout=2.0)
        time.sleep(1.8)
        self.configured = False
        self._rx_active = False

    def command(self, command: str, timeout_s: float = 1.2, stop_on: tuple[str, ...] = ("OK",)) -> str:
        self.serial.reset_input_buffer()
        self.serial.write((command + "\r\n").encode("ascii"))
        self.serial.flush()
        end = time.monotonic() + timeout_s
        lines: list[str] = []
        while time.monotonic() < end:
            raw = self.serial.readline()
            if not raw:
                continue
            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                continue
            lines.append(line)
            if _ERROR.search(line) or any(marker in line.upper() for marker in stop_on):
                break
        return "\n".join(lines).strip()

    def enter_test_mode(self) -> str:
        return self.command("AT+MODE=TEST", timeout_s=1.5, stop_on=("+TEST", "OK"))

    def configure(self) -> tuple[bool, str]:
        c = self.config
        command = (
            f"AT+TEST=RFCFG,{c.frequency_mhz},SF{c.spreading_factor},"
            f"{c.bandwidth_khz},{c.tx_preamble},{c.rx_preamble},{c.power_dbm},ON,OFF,OFF"
        )
        response = self.command(command, timeout_s=1.5, stop_on=("+TEST: RFCFG", "OK"))
        upper = response.upper()
        self.configured = bool(response) and not _ERROR.search(response) and ("+TEST: RFCFG" in upper or "OK" in upper)
        return self.configured, response

    def receive_window(self, timeout_s: float = 0.25) -> list[dict]:
        """Listen for a bounded half-duplex window, then leave the radio stopped.

        TEST-mode RXLRPKT is continuous. We explicitly issue TEST=STOP at the
        end so the caller can safely transmit or return to its normal loop.
        """
        if timeout_s <= 0 or timeout_s > 10:
            raise ValueError("receive window must be >0 and <=10 seconds")
        response = self.command(
            "AT+TEST=RXLRPKT", timeout_s=1.2,
            stop_on=("+TEST: RXLRPKT", "OK"),
        )
        if _ERROR.search(response):
            raise RuntimeError("LoRa-E5 could not enter RX mode: " + response[-300:])
        self._rx_active = True
        packets: list[dict] = []
        pending_rssi = None
        pending_snr = None
        deadline = time.monotonic() + timeout_s
        try:
            while time.monotonic() < deadline:
                raw = self.serial.readline()
                if not raw:
                    continue
                line = raw.decode("ascii", errors="ignore").strip()
                if not line:
                    continue
                meta = _RX_META.search(line)
                if meta:
                    pending_rssi, pending_snr = int(meta.group(1)), int(meta.group(2))
                    continue
                match = _RX_PACKET.search(line)
                if match:
                    try:
                        payload = bytes.fromhex(match.group(1).replace(" ", ""))
                    except ValueError:
                        pending_rssi = pending_snr = None
                        continue
                    packets.append({
                        "payload": payload,
                        "rssi_dbm": pending_rssi,
                        "snr_db": pending_snr,
                        "received_monotonic": time.monotonic(),
                    })
                    pending_rssi = pending_snr = None
        finally:
            stopped = self.command(
                "AT+TEST=STOP", timeout_s=1.0,
                stop_on=("+TEST: STOP", "OK"),
            )
            self._rx_active = False
            if _ERROR.search(stopped):
                raise RuntimeError("LoRa-E5 failed to leave RX mode: " + stopped[-300:])
        return packets

    def transmit(self, packet: bytes, timeout_s: float = 4.0) -> tuple[str, str]:
        if not isinstance(packet, bytes) or not packet or len(packet) > 250:
            raise ValueError("LoRa packet must contain 1-250 bytes")
        command = f'AT+TEST=TXLRPKT,"{packet.hex().upper()}"'
        if self._rx_active:
            stopped = self.command("AT+TEST=STOP", timeout_s=1.0, stop_on=("+TEST: STOP", "OK"))
            self._rx_active = False
            if _ERROR.search(stopped):
                raise RuntimeError("LoRa-E5 failed to stop RX before TX: " + stopped[-300:])
        response = self.command(command, timeout_s=timeout_s, stop_on=("TX DONE", "TX ERROR", "ERROR", "FAIL"))
        upper = response.upper()
        if "TX DONE" in upper:
            outcome = "confirmed"
        elif "TX ERROR" in upper or _ERROR.search(response):
            outcome = "failed"
        else:
            outcome = "unknown"
        return outcome, response

    def close(self) -> None:
        if self.serial and self.serial.is_open:
            self.serial.close()
