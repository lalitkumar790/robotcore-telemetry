from __future__ import annotations

import json
import os
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RCM_MAGIC = b"RCM1"
RCM_VERSION = 1
RCM_HEADER = struct.Struct(">4sBd")
RTPV2_PACKET_SIZE = 35


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MissionRecorder:
    """Legacy-compatible RCM samples plus an append-only JSONL audit trail."""

    def __init__(self, directory: str, experiment_id: str, radio_config: dict, gps_port: str, lora_port: str):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.start_unix = time.time()
        stem = datetime.now().strftime("mission_%Y%m%d_%H%M%S")
        candidate = self.directory / f"{stem}.rcm"
        suffix = 1
        while candidate.exists():
            candidate = self.directory / f"{stem}_{suffix:02d}.rcm"
            suffix += 1
        self.path = candidate
        self.events_path = self.path.with_name(self.path.stem + ".events.jsonl")
        self.manifest_path = self.path.with_name(self.path.stem + ".manifest.json")
        self._rcm = self.path.open("wb")
        self._events = self.events_path.open("a", encoding="utf-8", buffering=1)
        self._rcm.write(RCM_HEADER.pack(RCM_MAGIC, RCM_VERSION, self.start_unix))
        self._rcm.flush()
        self.experiment_id = experiment_id
        self.radio_config = radio_config
        self.gps_port = gps_port
        self.lora_port = lora_port
        self.samples_written = 0
        self.gps_no_fix_events = 0
        self.tx_confirmed = 0
        self.tx_failed = 0
        self.tx_unknown = 0
        self._event_id = 0
        self.closed = False
        self.write_event("mission_started", gps_port=gps_port, lora_port=lora_port, radio_config=radio_config)

    def write_sample(self, sequence: int, packet: bytes, gps: dict, imu_connected: bool, imu_age_s: float | None, imu_error: str | None) -> None:
        if len(packet) != RTPV2_PACKET_SIZE:
            raise ValueError(f"RTPv2 sample must be {RTPV2_PACKET_SIZE} bytes")
        self._rcm.write(packet)
        self._rcm.flush()
        self.samples_written += 1
        self.write_event(
            "sample_recorded", sequence=sequence, gps_valid=True, gps=gps,
            imu_connected=bool(imu_connected), imu_age_s=imu_age_s, imu_error=imu_error,
            tx_attempted=False, tx_outcome="pending",
        )

    def write_event(self, event_type: str, **fields: Any) -> None:
        if self.closed:
            return
        self._event_id += 1
        row = {
            "schema_version": "1.0.0", "event_id": self._event_id,
            "experiment_id": self.experiment_id, "mission_file": self.path.name,
            "event": event_type, "timestamp_utc": utc_now(),
            "timestamp_unix": time.time(), "monotonic_s": time.monotonic(),
        }
        row.update(fields)
        self._events.write(json.dumps(row, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        self._events.flush()

    def write_gps_missing(self, imu_connected: bool, imu_age_s: float | None, error: str | None) -> None:
        self.gps_no_fix_events += 1
        self.write_event("sample_skipped", reason="gps_no_fix", gps_valid=False,
                         imu_connected=bool(imu_connected), imu_age_s=imu_age_s,
                         gps_error=error, tx_attempted=False, tx_outcome="not_attempted")

    def write_tx_result(self, sequence: int, outcome: str, response: str, error: str | None = None) -> None:
        if outcome not in {"confirmed", "failed", "unknown", "not_attempted"}:
            raise ValueError(f"invalid TX outcome {outcome}")
        if outcome == "confirmed": self.tx_confirmed += 1
        elif outcome == "failed": self.tx_failed += 1
        elif outcome == "unknown": self.tx_unknown += 1
        self.write_event("tx_result", sequence=sequence, tx_attempted=outcome != "not_attempted",
                         tx_outcome=outcome, radio_response=response[-2000:], tx_error=error)

    def close(self) -> None:
        if self.closed:
            return
        ended = time.time()
        self.write_event("mission_stopped", samples_written=self.samples_written,
                         gps_no_fix_events=self.gps_no_fix_events, tx_confirmed=self.tx_confirmed,
                         tx_failed=self.tx_failed, tx_unknown=self.tx_unknown)
        self._rcm.flush()
        self._events.flush()
        self._rcm.close()
        self._events.close()
        manifest = {
            "schema_version": "1.0.0", "experiment_id": self.experiment_id,
            "mission_file": self.path.name, "events_file": self.events_path.name,
            "started_at_unix": self.start_unix, "ended_at_unix": ended,
            "duration_s": max(0.0, ended - self.start_unix), "sample_count": self.samples_written,
            "gps_no_fix_events": self.gps_no_fix_events,
            "tx_outcomes": {"confirmed": self.tx_confirmed, "failed": self.tx_failed, "unknown": self.tx_unknown},
            "radio_config": self.radio_config, "gps_port": self.gps_port, "lora_port": self.lora_port,
            "format": {"rcm_magic": "RCM1", "rcm_version": RCM_VERSION, "record_bytes": RTPV2_PACKET_SIZE},
        }
        temp = self.manifest_path.with_suffix(self.manifest_path.suffix + ".tmp")
        temp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, self.manifest_path)
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()
