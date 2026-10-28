from __future__ import annotations

import time
from typing import Any


def wait_for_fresh_imu(
    imu: Any,
    timeout_s: float,
    poll_interval_s: float = 0.25,
    report_interval_s: float = 5.0,
) -> bool:
    """Wait until the BLE client returns a fresh decoded reading or time out."""
    started = time.monotonic()
    deadline = started + max(0.0, timeout_s)
    last_report: float | None = None

    while True:
        reading, fresh, age, error = imu.get_reading()
        if fresh and reading is not None:
            if age is None:
                print("[IMU] Startup preflight passed; first fresh reading received.")
            else:
                print(f"[IMU] Startup preflight passed; first fresh reading age={age:.2f}s.")
            return True

        now = time.monotonic()
        elapsed = now - started
        if last_report is None or now - last_report >= report_interval_s:
            detail = error or "BLE scan/connect/notification setup is pending"
            print(
                f"[IMU] Waiting for first fresh reading "
                f"({elapsed:.0f}s/{timeout_s:.0f}s): {detail}"
            )
            last_report = now

        remaining = deadline - now
        if remaining <= 0:
            return False
        time.sleep(min(max(0.0, poll_interval_s), remaining))
