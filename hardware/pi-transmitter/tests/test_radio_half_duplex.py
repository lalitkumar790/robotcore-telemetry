import sys
import unittest
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radio import LoRaE5


class FakeSerial:
    def __init__(self):
        self.lines = deque()
        self.writes = []
        self.is_open = True

    def reset_input_buffer(self):
        self.lines.clear()

    def write(self, data):
        command = data.decode("ascii").strip()
        self.writes.append(command)
        if command == "AT+TEST=RXLRPKT":
            self.lines.extend([
                b"+TEST: RXLRPKT\r\n",
                b"+TEST: LEN:3, RSSI:-91, SNR:7\r\n",
                b'+TEST: RX "414243"\r\n',
            ])
        elif command == "AT+TEST=STOP":
            self.lines.append(b"+TEST: STOP\r\n")
        elif command.startswith("AT+TEST=TXLRPKT"):
            self.lines.extend([b"+TEST: TXLRPKT\r\n", b"+TEST: TX DONE\r\n"])
        return len(data)

    def flush(self):
        pass

    def readline(self):
        return self.lines.popleft() if self.lines else b""

    def close(self):
        self.is_open = False


class LoRaHalfDuplexTests(unittest.TestCase):
    def make_radio(self):
        radio = LoRaE5.__new__(LoRaE5)
        radio.serial = FakeSerial()
        radio._rx_active = False
        radio.configured = True
        return radio

    def test_receive_window_parses_payload_and_signal_metadata_then_stops(self):
        radio = self.make_radio()
        packets = radio.receive_window(0.01)
        self.assertEqual(len(packets), 1)
        self.assertEqual(packets[0]["payload"], b"ABC")
        self.assertEqual(packets[0]["rssi_dbm"], -91)
        self.assertEqual(packets[0]["snr_db"], 7)
        self.assertFalse(radio._rx_active)
        self.assertEqual(radio.serial.writes[0], "AT+TEST=RXLRPKT")
        self.assertEqual(radio.serial.writes[-1], "AT+TEST=STOP")

    def test_transmit_enforces_payload_size(self):
        radio = self.make_radio()
        with self.assertRaises(ValueError):
            radio.transmit(b"x" * 251)

    def test_transmit_stops_active_receive_before_sending(self):
        radio = self.make_radio()
        radio._rx_active = True
        outcome, response = radio.transmit(b"command")
        self.assertEqual(outcome, "confirmed")
        self.assertIn("TX DONE", response)
        self.assertEqual(radio.serial.writes[0], "AT+TEST=STOP")
        self.assertTrue(radio.serial.writes[1].startswith('AT+TEST=TXLRPKT,"'))

    def test_invalid_receive_window_rejected(self):
        radio = self.make_radio()
        for value in (0, -1, 10.1):
            with self.assertRaises(ValueError):
                radio.receive_window(value)


if __name__ == "__main__":
    unittest.main()
