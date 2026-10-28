from __future__ import annotations

import re
import time

import serial

from config import LORA_BAUD, RadioConfig

_ERROR = re.compile(r"\b(ERROR|FAIL|ERR)\b", re.IGNORECASE)


class LoRaE5:
    def __init__(self, port: str, config: RadioConfig):
        self.port = port
        self.config = config
        self.serial = serial.Serial(port=port, baudrate=LORA_BAUD, timeout=0.2, write_timeout=2.0)
        time.sleep(1.8)
        self.configured = False

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
        self.configured = bool(response) and not _ERROR.search(response)
        return self.configured, response

    def transmit(self, packet: bytes, timeout_s: float = 4.0) -> tuple[str, str]:
        command = f'AT+TEST=TXLRPKT,"{packet.hex().upper()}"'
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
