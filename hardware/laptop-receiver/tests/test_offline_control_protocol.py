import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from offline_control_protocol import (
    ControlReplayGuard,
    OfflineControlError,
    decode_control_message,
    encode_control_message,
)


class OfflineControlProtocolTests(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        self.start = {
            "kind": "START", "device_id": "pi-field-01",
            "request_id": "req-0001", "counter": 1,
            "session_id": "session-001", "experiment_id": "lora-test-01",
        }

    def test_authenticated_round_trip_and_lora_size(self):
        packet = encode_control_message(self.start, self.key)
        self.assertLessEqual(len(packet), 250)
        self.assertEqual(decode_control_message(packet, self.key), self.start)

    def test_wrong_key_and_tampering_rejected(self):
        packet = encode_control_message(self.start, self.key)
        with self.assertRaises(OfflineControlError):
            decode_control_message(packet, os.urandom(32))
        damaged = packet[:-1] + bytes([packet[-1] ^ 1])
        with self.assertRaises(OfflineControlError):
            decode_control_message(damaged, self.key)

    def test_invalid_command_fields_rejected(self):
        for update in (
            {"kind": "EXEC"},
            {"counter": 0},
            {"session_id": "../unsafe"},
            {"experiment_id": None},
        ):
            message = dict(self.start)
            message.update(update)
            with self.assertRaises(OfflineControlError):
                encode_control_message(message, self.key)

    def test_stop_and_status_shapes(self):
        stop = {"kind": "STOP", "device_id": "pi-field-01", "request_id": "req-2",
                "counter": 2, "session_id": "session-001"}
        status = {"kind": "STATUS", "device_id": "pi-field-01", "request_id": "req-3",
                  "counter": 3}
        decoded_stop = decode_control_message(encode_control_message(stop, self.key), self.key)
        self.assertEqual(decoded_stop["kind"], "STOP")
        self.assertEqual(decoded_stop["session_id"], "session-001")
        self.assertIsNone(decoded_stop["experiment_id"])
        decoded_status = decode_control_message(encode_control_message(status, self.key), self.key)
        self.assertEqual(decoded_status["kind"], "STATUS")
        self.assertIsNone(decoded_status["session_id"])
        self.assertIsNone(decoded_status["experiment_id"])

    def test_retries_are_idempotent_and_replays_rejected(self):
        guard = ControlReplayGuard()
        message = decode_control_message(encode_control_message(self.start, self.key), self.key)
        first = guard.accept(message)
        retry = guard.accept(message)
        self.assertTrue(first.accepted)
        self.assertFalse(first.duplicate)
        self.assertTrue(retry.accepted)
        self.assertTrue(retry.duplicate)

        replay = dict(message, request_id="different-request")
        decision = guard.accept(replay)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "stale_or_replayed_counter")

    def test_request_id_cannot_be_reused_for_different_command(self):
        guard = ControlReplayGuard()
        message = decode_control_message(encode_control_message(self.start, self.key), self.key)
        guard.accept(message)
        changed = dict(message, kind="STOP", counter=2)
        decision = guard.accept(changed)
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "request_id_reused_with_different_content")

    def test_persisted_high_water_rejects_old_packets_after_restart(self):
        guard = ControlReplayGuard(high_water=12)
        old = dict(self.start, counter=12)
        decision = guard.accept(old)
        self.assertFalse(decision.accepted)


if __name__ == "__main__":
    unittest.main()
