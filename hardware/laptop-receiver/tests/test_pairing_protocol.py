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
