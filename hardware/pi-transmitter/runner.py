from __future__ import annotations

import argparse
import os
import time

from config import EXPERIMENT_ID, MISSIONS_DIR, TX_INTERVAL, RadioConfig
from device_discovery import print_serial_candidates, select_serial_port
from gps import GPS
from mission_recorder import MissionRecorder
from radio import LoRaE5
from rtp2 import encode_rtpv2
from witmotion import WitMotion
from imu_preflight import wait_for_fresh_imu


def parse_args():
    parser = argparse.ArgumentParser(description="RobotCore Pi GPS/WitMotion/LoRa field transmitter")
    parser.add_argument("--gps-port", help="explicit GPS serial device; overrides ROBOTCORE_GPS_PORT")
    parser.add_argument("--lora-port", help="explicit LoRa-E5 serial device; overrides ROBOTCORE_LORA_PORT")
    parser.add_argument("--list-devices", action="store_true", help="list USB serial devices and exit")
    parser.add_argument("--interval", type=float, default=TX_INTERVAL, help="seconds between samples")
    parser.add_argument(
        "--imu-startup-timeout", type=float, default=90.0,
        help="seconds to wait for a fresh WT901BLE68 sample before recording or transmitting (default: 90)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_devices:
        print_serial_candidates()
        return 0
    if args.interval < 0.5:
        raise SystemExit("Sampling interval must be at least 0.5 seconds.")
    if args.imu_startup_timeout < 1.0:
        raise SystemExit("IMU startup timeout must be at least 1 second.")

    if args.gps_port:
        os.environ["ROBOTCORE_GPS_PORT"] = args.gps_port
    if args.lora_port:
        os.environ["ROBOTCORE_LORA_PORT"] = args.lora_port

    print("=" * 72)
    print("RobotCore Pi Transmitter · field capture")
    print("RTPv2 on-air bytes remain compatible with the current receiver.")
    print("=" * 72)
    print_serial_candidates()
    gps_port = select_serial_port("gps")
    try:
        lora_port = select_serial_port("lora", exclude={gps_port})
    except Exception as error:
        # GPS+IMU recording remains valuable even when the TX radio is missing
        # or Windows/Linux USB discovery cannot safely identify it. Never
        # pretend a packet was transmitted; manifest and sidecar record absence.
        lora_port = "UNAVAILABLE"
        print(f"[LoRa] Transmitter port unavailable: {error}")
        print("[LoRa] Continuing with local mission recording only; no radio TX will be attempted.")

    print(f"[GPS] Selected {gps_port}")
    print(f"[LoRa] Selected {lora_port}")
    print("[IMU] Starting WT901BLE68 scan/reconnect loop in background")

    radio_config = RadioConfig()
    gps = GPS(gps_port, other_port=None if lora_port == "UNAVAILABLE" else lora_port)
    imu = WitMotion()
    try:
        lora = LoRaE5(lora_port, radio_config) if lora_port != "UNAVAILABLE" else None
    except Exception as error:
        lora = None
        print(f"[LoRa] Could not open transmitter port; local mission capture continues: {error}")

    radio_event_type = None
    radio_event_fields: dict = {}
    if lora is not None:
        try:
            mode_response = lora.enter_test_mode()
            confirmed, config_response = lora.configure()
            radio_event_type = "radio_config"
            radio_event_fields = {
                "mode_response": mode_response,
                "radio_config_response": config_response,
                "config_confirmed": confirmed,
            }
            print("[LoRa] Test mode response:", mode_response or "(no text response)")
            print("[LoRa] Config response:", config_response or "(no text response)")
            if not confirmed:
                print("[LoRa] Radio config response was inconclusive. TX is best-effort and logged.")
        except Exception as error:
            radio_event_type = "radio_config_error"
            radio_event_fields = {"error": str(error)}
            print(f"[LoRa] Configuration failed; TX disabled but mission capture continues: {error}")
            try:
                lora.close()
            except Exception:
                pass
            lora = None

    print(
        f"[IMU] Preflight: waiting up to {args.imu_startup_timeout:.0f}s for a fresh WT901BLE68 reading. "
        "No mission sample or LoRa packet will be produced before this passes."
    )
    try:
        imu_ready = wait_for_fresh_imu(imu, args.imu_startup_timeout)
    except KeyboardInterrupt:
        print("\\n[FIELD] Startup cancelled before mission recording began.")
        gps.close()
        imu.close()
        if lora is not None:
            lora.close()
        return 130

    if not imu_ready:
        print(
            f"[IMU] No fresh reading received within {args.imu_startup_timeout:.0f}s. "
            "Aborting without recording zero-filled startup samples."
        )
        gps.close()
        imu.close()
        if lora is not None:
            lora.close()
        return 2

    recorder = MissionRecorder(MISSIONS_DIR, EXPERIMENT_ID, radio_config.as_dict(), gps_port, lora_port)
    if radio_event_type is not None:
        recorder.write_event(radio_event_type, **radio_event_fields)

    print(f"[MISSION] RCM: {recorder.path}")
    print(f"[MISSION] Events: {recorder.events_path}")
    print(f"[MISSION] Manifest: {recorder.manifest_path}")
    print("[GPS] Waiting for a valid RMC fix. No invalid/old coordinate will be presented as fresh.")
    print("[FIELD] Ctrl+C stops safely; keep the three mission files together.")

    sequence = 0
    no_fix_count = 0
    try:
        while True:
            started = time.monotonic()
            fix = gps.read_fix(timeout_s=min(1.6, args.interval))
            if fix is None:
                no_fix_count += 1
                _reading, imu_connected, imu_age, _imu_error = imu.get_reading()
                recorder.write_gps_missing(imu_connected, imu_age, gps.last_error)
                if no_fix_count == 1 or no_fix_count % 5 == 0:
                    print(f"[GPS] No valid fix yet (attempt {no_fix_count}). "
                          f"IMU={'fresh' if imu_connected else 'waiting/stale'}; skip recorded.")
                if gps.last_error:
                    gps.try_reconnect()
                time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
                continue

            no_fix_count = 0
            sequence = sequence % 65535 + 1
            imu_reading, imu_connected, imu_age, imu_error = imu.get_reading()
            packet = encode_rtpv2(sequence, fix.latitude, fix.longitude, fix.speed_kmh, imu_reading)
            recorder.write_sample(sequence, packet, fix.as_dict(), imu_connected, imu_age, imu_error)

            outcome, response, tx_exception = "not_attempted", "", None
            if lora is not None:
                recorder.write_event("tx_attempt", sequence=sequence, tx_attempted=True, tx_outcome="pending")
                try:
                    outcome, response = lora.transmit(packet)
                except Exception as error:
                    outcome, tx_exception = "failed", str(error)
                    response = ""
                recorder.write_tx_result(sequence, outcome, response, tx_exception)
            else:
                recorder.write_tx_result(sequence, "not_attempted", "", "LoRa transmitter unavailable")

            imu_label = "fresh" if imu_connected else "not connected / stale; zero fields used for RTPv2 compatibility"
            print(f"[TX {sequence:05d}] {fix.latitude:.6f}, {fix.longitude:.6f} | "
                  f"{fix.speed_kmh:.2f} km/h | IMU {imu_label} | TX {outcome} | samples {recorder.samples_written}")
            if response:
                for line in response.splitlines()[-3:]:
                    print("  " + line)
            time.sleep(max(0.0, args.interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        print("\n[FIELD] Stopping transmitter and flushing local records...")
    finally:
        recorder.close()
        gps.close()
        imu.close()
        if lora is not None:
            lora.close()
        print(f"[MISSION] Saved {recorder.samples_written} samples.")
        print(f"[MISSION] Keep together: {recorder.path}, {recorder.events_path}, {recorder.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
