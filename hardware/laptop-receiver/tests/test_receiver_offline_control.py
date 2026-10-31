import os
import queue
import threading
import unittest

from receiver import ReceiverWorker


class FakeSerial:
    def __init__(self):
        self.is_open = True
        self.commands = []
        self._response = []

    def reset_input_buffer(self):
        self._response = []

    def write(self, data):
        command = data.decode("ascii").strip()
        self.commands.append(command)
        if command == "AT+TEST=STOP":
            self._response = [b"OK\r\n"]
        elif command.startswith("AT+TEST=TXLRPKT"):
            self._response = [b"TX DONE\r\n"]
        elif command == "AT+TEST=RXLRPKT":
            self._response = [b"OK\r\n"]

    def flush(self):
        pass

    def readline(self):
        return self._response.pop(0) if self._response else b""


class ReceiverOfflineDownlinkTests(unittest.TestCase):
    def test_control_downlink_runs_only_through_worker_serial_owner(self):
        worker = ReceiverWorker(
            port="COM12", log_dir="logs", radio={}, on_packet=lambda _record: None,
            on_status=lambda: None, managed_sessions=True, pairing_key=os.urandom(32),
        )
        fake = FakeSerial()
        worker.serial_port = fake
        packet = b"RCC1-test-packet"
        done = threading.Event()
        item = {"packet": packet, "done": done, "result": None, "error": None}
        worker._control_tx_queue.put(item)

        worker._service_control_tx()

        self.assertTrue(done.is_set())
        self.assertIsNone(item["error"])
        self.assertIn("TX DONE", item["result"])
        self.assertEqual(fake.commands[0], "AT+TEST=STOP")
        self.assertEqual(fake.commands[1], 'AT+TEST=TXLRPKT,"' + packet.hex().upper() + '"')
        self.assertEqual(fake.commands[2], "AT+TEST=RXLRPKT")
        self.assertEqual(worker.control_packets_sent, 1)


if __name__ == "__main__":
    unittest.main()
