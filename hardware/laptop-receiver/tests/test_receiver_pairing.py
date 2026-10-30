import os
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "common"))

from pairing_protocol import encode_pairing_beacon
from receiver import ReceiverWorker


class ReceiverPairingBeaconTests(unittest.TestCase):
    def make_worker(self, key, received):
        return ReceiverWorker(
            port="COM8",
            log_dir="logs",
            radio={},
            on_packet=lambda _record: self.fail("Pairing beacons must not be emitted as telemetry."),
            on_status=lambda: None,
            experiment_id="UNLABELLED",
            managed_sessions=True,
            on_pairing=received.append,
            pairing_key=key,
        )

    def descriptor(self):
        now = int(time.time())
        return {
            "v": 1,
            "u": "https://quiet-marble-otter.trycloudflare.com",
            "t": "R7qKJc9jUOZlJ4_Jp4nWx7FWeqYc9xVg_9C2j0dKxyA",
            "d": "pi-field-01",
            "i": now,
            "e": now + 45,
        }

    def test_valid_beacon_is_delivered_to_pairing_callback_not_pdr_counters(self):
        key = os.urandom(32)
        received = []
        worker = self.make_worker(key, received)
        packet = encode_pairing_beacon(self.descriptor(), key)

        worker._process_packet(packet)

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["device_id"], "pi-field-01")
        self.assertEqual(worker.packets_received, 0)
        self.assertEqual(worker.packets_corrupt, 0)
        self.assertEqual(worker.pairing_received, 1)

    def test_beacon_with_wrong_pairing_key_is_rejected_not_counted_as_corrupt_telemetry(self):
        received = []
        worker = self.make_worker(os.urandom(32), received)
        packet = encode_pairing_beacon(self.descriptor(), os.urandom(32))

        worker._process_packet(packet)

        self.assertEqual(received, [])
        self.assertEqual(worker.packets_received, 0)
        self.assertEqual(worker.packets_corrupt, 0)
        self.assertEqual(worker.pairing_rejected, 1)
        self.assertIn("authentication failed", worker.last_pairing_error)


if __name__ == "__main__":
    unittest.main()
