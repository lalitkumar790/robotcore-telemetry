from __future__ import annotations

import argparse
import os
import time
import sys
from pathlib import Path

from config import EXPERIMENT_ID, MISSIONS_DIR, TX_INTERVAL, RadioConfig
from device_discovery import print_serial_candidates, select_serial_port
from gps import GPS
from mission_recorder import MissionRecorder
from radio import LoRaE5
from rtp2 import encode_rtpv2
from witmotion import WitMotion
from imu_preflight import wait_for_fresh_imu

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from pairing_protocol import load_pairing_key
from offline_control_protocol import OfflineControlError, decode_control_message
from offline_control_runtime import PersistentControlState


def parse_args():
    parser = argparse.ArgumentParser(description="RobotCore Pi GPS/WitMotion/LoRa field transmitter")
    parser.add_argument("--gps-port", help="explicit GPS serial device; overrides ROBOTCORE_GPS_PORT")
    parser.add_argument("--lora-port", help="explicit LoRa-E5 serial device; overrides ROBOTCORE_LORA_PORT")
    parser.add_argument("--list-devices", action="store_true", help="list USB serial devices and exit")
    parser.add_argument(
        "--require-lora", action="store_true",
        help="abort if the LoRa transmitter is not detected (recommended for unattended field runs)",
    )
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
        if args.require_lora:
            raise SystemExit(f"[LoRa] Required transmitter port unavailable; refusing a radio-less field run: {error}")
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
        if args.require_lora:
            gps.close()
            imu.close()
            raise SystemExit(f"[LoRa] Could not open required transmitter port; aborting field run: {error}")
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
                if args.require_lora:
                    gps.close()
                    imu.close()
                    lora.close()
                    raise SystemExit("[LoRa] Required radio configuration was not acknowledged; aborting field run.")
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
            if args.require_lora:
                gps.close()
                imu.close()
                raise SystemExit("[LoRa] Required radio setup failed; aborting field run.")

    print(
        f"[IMU] Preflight: waiting up to {args.imu_startup_timeout:.0f}s for a fresh WT901BLE68 reading. "
        "No mission sample or LoRa packet will be produced before this passes."
    )
    try:
        imu_ready = wait_for_fresh_imu(imu, args.imu_startup_timeout)
    except KeyboardInterrupt:
        print("\n[FIELD] Startup cancelled before mission recording began.")
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


    control_key = None
    control_state = None
    if lora is not None:
        try:
            control_key = load_pairing_key(os.getenv("ROBOTCORE_PAIRING_KEY_FILE", "/etc/robotcore-pairing.key"))
            state_path = os.getenv("ROBOTCORE_OFFLINE_CONTROL_STATE", str(Path(MISSIONS_DIR) / ".offline-control.json"))
            control_state = PersistentControlState(state_path)
        except Exception as error:
            print(f"[CONTROL] Offline command channel disabled: {error}")

    recorder = MissionRecorder(MISSIONS_DIR, EXPERIMENT_ID, radio_config.as_dict(), gps_port, lora_port)

    def poll_offline_control() -> bool:
        if lora is None or control_key is None or control_state is None:
            return False
        try:
            for item in lora.receive_window(timeout_s=0.8):
                payload = item.get("payload", b"")
                if not payload.startswith(b"RCC1"):
                    continue
                try:
                    message = decode_control_message(payload, control_key)
                except OfflineControlError as error:
                    recorder.write_event("offline_control_rejected", reason=str(error))
                    continue
                expected_device = os.getenv("ROBOTCORE_DEVICE_ID", "").strip()
                if expected_device and message.get("device_id") != expected_device:
                    continue
                if message.get("kind") not in {"STOP", "STATUS", "START"}:
                    continue
                decision, cached = control_state.accept(message)
                if decision == "duplicate":
                    if cached:
                        outcome, response = lora.transmit(cached, timeout_s=5.0)
                        recorder.write_event("offline_control_duplicate_reply", request_id=message["request_id"], tx_outcome=outcome, modem_response=response[-300:])
                    continue
                if decision != "new":
                    recorder.write_event("offline_control_rejected", request_id=message.get("request_id"), reason="stale_or_replayed")
                    continue
                kind = message["kind"]
                if kind == "STOP" and message.get("session_id") == os.getenv("ROBOTCORE_SESSION_ID"):
                    reply_kind, stop_requested = "ACK", True
                elif kind == "STATUS":
                    reply_kind, stop_requested = "ACK", False
                else:
                    reply_kind, stop_requested = "NACK", False
                reply = control_state.reply(message, reply_kind, control_key)
                outcome, response = lora.transmit(reply, timeout_s=5.0)
                recorder.write_event(
                    "offline_control_handled", kind=kind, request_id=message["request_id"],
                    reply_kind=reply_kind, tx_outcome=outcome, modem_response=response[-300:],
                )
                if stop_requested and outcome == "confirmed":
                    print("[CONTROL] Authenticated offline STOP received; stopping mission cleanly.")
                    return True
        except Exception as error:
            recorder.write_event("offline_control_error", error=str(error))
            print(f"[CONTROL] Offline command polling error: {error}")
        return False

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
                if poll_offline_control():
                    break
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
            if poll_offline_control():
                break
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
