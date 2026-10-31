import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "common"))

from offline_control_protocol import encode_control_message
from offline_control_runtime import PersistentControlState
from receiver import ReceiverWorker


class PersistentControlStateTests(unittest.TestCase):
    def test_counter_persists_and_duplicate_returns_exact_cached_reply(self):
        key = os.urandom(32)
        request = {
            "kind": "START", "device_id": "pi-test", "request_id": "req-1",
            "counter": 1, "session_id": "session-1", "experiment_id": "exp-1",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.json"
            first = PersistentControlState(path)
            self.assertEqual(first.accept(request), ("new", None))
            reply = first.reply(request, "ACK", key)
            restarted = PersistentControlState(path)
            decision, cached = restarted.accept(request)
            self.assertEqual(decision, "duplicate")
            self.assertEqual(cached, reply)
            stale = dict(request, request_id="req-old", counter=1)
            self.assertEqual(restarted.accept(stale), ("rejected", None))

    def test_reply_packet_is_authenticated_and_correlates_request(self):
        key = os.urandom(32)
        request = {
            "kind": "STOP", "device_id": "pi-test", "request_id": "req-stop",
            "counter": 2, "session_id": "session-1", "experiment_id": "exp-1",
        }
        with tempfile.TemporaryDirectory() as directory:
            store = PersistentControlState(Path(directory) / "control.json")
            store.accept(request)
            packet = store.reply(request, "ACK", key)
            worker = ReceiverWorker(
                port="COM8", log_dir=directory, radio={}, on_packet=lambda _record: None,
                on_status=lambda: None, managed_sessions=True, pairing_key=key,
            )
            waiter = {"event": threading.Event(), "ack": None, "error": None}
            worker._control_waiters["req-stop"] = waiter
            self.assertTrue(worker._process_control_packet(packet))
            self.assertTrue(waiter["event"].is_set())
            self.assertEqual(waiter["ack"]["kind"], "ACK")
            self.assertEqual(waiter["ack"]["request_id"], "req-stop")
            self.assertEqual(worker.control_acks_received, 1)


if __name__ == "__main__":
    unittest.main()
