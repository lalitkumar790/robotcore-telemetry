import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "common"))

from pairing_protocol import (
    PairingError,
    decode_pairing_beacon,
    encode_pairing_beacon,
    is_pairing_beacon,
    is_status_beacon,
    encode_status_beacon,
    decode_status_beacon,
    load_pairing_key,
)


class PairingProtocolTests(unittest.TestCase):
    def setUp(self):
        self.key = os.urandom(32)
        now = int(time.time())
        self.descriptor = {
            "v": 1,
            "u": "https://quiet-marble-otter.trycloudflare.com",
            "t": "R7qKJc9jUOZlJ4_Jp4nWx7FWeqYc9xVg_9C2j0dKxyA",
            "d": "pi-field-01",
            "i": now,
            "e": now + 45,
        }

    def test_round_trip_is_encrypted_authenticated_and_under_lora_e5_limit(self):
        packet = encode_pairing_beacon(self.descriptor, self.key)
        self.assertTrue(is_pairing_beacon(packet))
        self.assertLessEqual(len(packet), 250)
        decoded = decode_pairing_beacon(packet, self.key)
        self.assertEqual(decoded["tunnel_url"], self.descriptor["u"])
        self.assertEqual(decoded["control_token"], self.descriptor["t"])
        self.assertEqual(decoded["device_id"], self.descriptor["d"])

    def test_wrong_key_and_tampering_are_rejected(self):
        packet = encode_pairing_beacon(self.descriptor, self.key)
        with self.assertRaises(PairingError):
            decode_pairing_beacon(packet, os.urandom(32))
        corrupted = packet[:-1] + bytes([packet[-1] ^ 1])
        with self.assertRaises(PairingError):
            decode_pairing_beacon(corrupted, self.key)

    def test_expired_beacon_is_rejected(self):
        packet = encode_pairing_beacon(self.descriptor, self.key)
        with self.assertRaises(PairingError):
            decode_pairing_beacon(packet, self.key, now=self.descriptor["e"] + 1)

    def test_status_beacon_round_trip_reports_internet_retry_without_credentials(self):
        now = int(time.time())
        status = {
            "device_id": "pi-field-01",
            "state": "waiting_for_internet",
            "internet_connected": False,
            "tunnel_state": "waiting_for_internet",
            "last_error": "Internet probe timed out",
            "issued_at": now,
            "valid_until": now + 30,
        }
        packet = encode_status_beacon(status, self.key)
        self.assertTrue(is_status_beacon(packet))
        decoded = decode_status_beacon(packet, self.key)
        self.assertEqual(decoded["state"], "waiting_for_internet")
        self.assertFalse(decoded["internet_connected"])
        self.assertEqual(decoded["last_error"], "Internet probe timed out")
        self.assertNotIn("control_token", decoded)
        self.assertLessEqual(len(packet), 250)

    def test_status_beacon_rejects_wrong_key(self):
        now = int(time.time())
        status = {
            "device_id": "pi-field-01",
            "state": "connecting_tunnel",
            "internet_connected": True,
            "tunnel_state": "connecting",
            "issued_at": now,
            "valid_until": now + 30,
        }
        packet = encode_status_beacon(status, self.key)
        with self.assertRaises(PairingError):
            decode_status_beacon(packet, os.urandom(32))

    def test_key_loader_accepts_hex_and_base64(self):
        import base64
        import tempfile
        for data in (self.key.hex().encode(), base64.urlsafe_b64encode(self.key)):
            with tempfile.NamedTemporaryFile() as file:
                file.write(data)
                file.flush()
                self.assertEqual(load_pairing_key(file.name), self.key)


if __name__ == "__main__":
    unittest.main()
