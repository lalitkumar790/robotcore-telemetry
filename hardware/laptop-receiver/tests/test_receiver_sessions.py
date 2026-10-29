import tempfile
import unittest
from pathlib import Path

from receiver import ReceiverWorker


class ManagedReceiverSessionTests(unittest.TestCase):
    def test_csv_is_created_only_when_field_session_starts_and_uses_shared_id(self):
        with tempfile.TemporaryDirectory() as temp:
            worker = ReceiverWorker(
                port="COM8",
                log_dir=temp,
                radio={},
                on_packet=lambda _record: None,
                on_status=lambda: None,
                experiment_id="UNASSIGNED",
                managed_sessions=True,
            )
            self.assertFalse(worker.capture_active)
            self.assertIsNone(worker.log_path)

            status = worker.begin_field_session("MANIT-20261030-A", "RC-20261030T010203-AB123")
            self.assertTrue(status["capture_active"])
            self.assertEqual(status["field_session_id"], "RC-20261030T010203-AB123")
            self.assertIn("MANIT-20261030-A_RC-20261030T010203-AB123", Path(status["log_file"]).name)
            self.assertTrue(Path(status["log_file"]).exists())

            stopped = worker.end_field_session()
            self.assertFalse(stopped["capture_active"])
            self.assertTrue(Path(status["log_file"]).exists())
            header = Path(status["log_file"]).read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("Field Session ID", header)


if __name__ == "__main__":
    unittest.main()
