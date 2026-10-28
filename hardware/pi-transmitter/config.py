import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be numeric")


GPS_BAUD = _int_env("ROBOTCORE_GPS_BAUD", 9600)
LORA_BAUD = _int_env("ROBOTCORE_LORA_BAUD", 9600)
GPS_READ_TIMEOUT = _float_env("ROBOTCORE_GPS_READ_TIMEOUT", 0.5)
TX_INTERVAL = _float_env("ROBOTCORE_TX_INTERVAL", 2.0)
MISSIONS_DIR = os.getenv("ROBOTCORE_MISSIONS_DIR", "missions")
EXPERIMENT_ID = os.getenv("ROBOTCORE_EXPERIMENT_ID", "").strip() or "UNLABELLED"
IMU_ADDRESS = os.getenv("ROBOTCORE_IMU_ADDRESS", "").strip()
IMU_NAME_HINT = os.getenv("ROBOTCORE_IMU_NAME", "WT901BLE68").strip()

GPS_VID_PID = (0x1A86, 0x7523)
LORA_VID_PID = (0x10C4, 0xEA60)


@dataclass(frozen=True)
class RadioConfig:
    frequency_mhz: int = _int_env("ROBOTCORE_FREQUENCY_MHZ", 865)
    spreading_factor: int = _int_env("ROBOTCORE_SPREADING_FACTOR", 7)
    bandwidth_khz: int = _int_env("ROBOTCORE_BANDWIDTH_KHZ", 125)
    tx_preamble: int = _int_env("ROBOTCORE_TX_PREAMBLE", 12)
    rx_preamble: int = _int_env("ROBOTCORE_RX_PREAMBLE", 15)
    power_dbm: int = _int_env("ROBOTCORE_TX_POWER_DBM", 14)

    def as_dict(self) -> dict:
        return {
            "frequency_mhz": self.frequency_mhz,
            "spreading_factor": self.spreading_factor,
            "bandwidth_khz": self.bandwidth_khz,
            "tx_preamble": self.tx_preamble,
            "rx_preamble": self.rx_preamble,
            "power_dbm": self.power_dbm,
        }
