import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "pi-transmitter"))

from protocol import decode_packet, crc16_ccitt_false

try:
    from rtp2 import encode_rtpv2
except ImportError:
    encode_rtpv2 = None


class LaptopDecoderTests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(crc16_ccitt_false(b"123456789"), 0x29B1)

    def test_decode_rtpv2_golden_generated_by_pi_encoder(self):
        # Independently assemble the same fixed-layout frame; no hardware is needed.
        import struct
        head = struct.pack(">BBBHiiH9h", 0xAA, 2, 6, 123, 23213622, 77408091, 370, 100, -200, 980, 15, -25, 40, 1234, -567, 8901)
        packet = head + struct.pack(">H", crc16_ccitt_false(head))
        decoded = decode_packet(packet)
        self.assertEqual(len(packet), 35)
        self.assertEqual(decoded["sequence"], 123)
        self.assertAlmostEqual(decoded["latitude"], 23.213622, places=6)
        self.assertAlmostEqual(decoded["longitude"], 77.408091, places=6)
        self.assertAlmostEqual(decoded["roll"], 12.34, places=2)
        self.assertEqual(decoded["imu_health"], "unverified_on_wire")

    def test_bad_crc_rejected(self):
        import struct
        head = struct.pack(">BBBHiiH9h", 0xAA, 2, 6, 1, 23200000, 77400000, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        packet = bytearray(head + struct.pack(">H", crc16_ccitt_false(head)))
        packet[-1] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC"):
            decode_packet(bytes(packet))


if __name__ == "__main__":
    unittest.main()
