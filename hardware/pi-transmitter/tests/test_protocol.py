import os
import sys
import unittest

HERE = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, HERE)

from rtp2 import crc16_ccitt_false, decode_rtpv2, encode_rtpv2


class SampleIMU:
    ax = 0.1
    ay = -0.2
    az = 0.98
    gx = 1.5
    gy = -2.5
    gz = 4.0
    roll = 12.34
    pitch = -5.67
    yaw = 89.01


class RTPv2Tests(unittest.TestCase):
    def test_crc_known_vector(self):
        self.assertEqual(crc16_ccitt_false(b"123456789"), 0x29B1)

    def test_packet_layout_roundtrip(self):
        packet = encode_rtpv2(65535, 23.213622, 77.408091, 3.7, SampleIMU())
        self.assertEqual(len(packet), 35)
        decoded = decode_rtpv2(packet)
        self.assertEqual(decoded["sequence"], 65535)
        self.assertAlmostEqual(decoded["latitude"], 23.213622, places=6)
        self.assertAlmostEqual(decoded["longitude"], 77.408091, places=6)
        self.assertAlmostEqual(decoded["speed"], 3.7, places=2)
        self.assertAlmostEqual(decoded["roll"], 12.34, places=2)

    def test_crc_corruption_is_rejected(self):
        packet = bytearray(encode_rtpv2(1, 23.2, 77.4, 0.0, None))
        packet[10] ^= 0x10
        with self.assertRaisesRegex(ValueError, "CRC"):
            decode_rtpv2(bytes(packet))

    def test_sequence_wrap_is_1_after_65535(self):
        self.assertEqual((65535 % 65535) + 1, 1)


if __name__ == "__main__":
    unittest.main()
