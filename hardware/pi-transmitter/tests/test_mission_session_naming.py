import json
import os
import tempfile
import unittest
from unittest.mock import patch

from mission_recorder import MissionRecorder


class MissionSessionNamingTests(unittest.TestCase):
    def test_session_id_is_shared_by_mission_filename_manifest_and_events(self):
        session_id = "RC-20261030T012345-AB12C"
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"ROBOTCORE_SESSION_ID": session_id}):
            recorder = MissionRecorder(
                directory=temp,
                experiment_id="MANIT-20261030-A",
                radio_config={"frequency_mhz": 865, "spreading_factor": 7},
                gps_port="/dev/ttyUSB0",
                lora_port="/dev/ttyUSB1",
            )
            packet = bytes([0xAA]) + bytes(34)
            recorder.write_sample(
                sequence=1,
                packet=packet,
                gps={"latitude": 23.2, "longitude": 77.4, "speed_kmh": 0.0},
                imu_connected=True,
                imu_age_s=0.02,
                imu_error=None,
            )
            recorder.write_tx_result(1, "confirmed", "+TEST: TX DONE")
            recorder.close()

            self.assertIn(session_id, recorder.path.name)
            self.assertTrue(recorder.events_path.exists())
            self.assertTrue(recorder.manifest_path.exists())
            manifest = json.loads(recorder.manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["session_id"], session_id)
            events = [json.loads(line) for line in recorder.events_path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(events)
            self.assertTrue(all(row["session_id"] == session_id for row in events))
            self.assertEqual(manifest["sample_count"], 1)
            self.assertEqual(manifest["tx_outcomes"]["confirmed"], 1)

    def test_legacy_filename_remains_valid_when_session_id_is_unset(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            recorder = MissionRecorder(
                directory=temp,
                experiment_id="LEGACY",
                radio_config={},
                gps_port="/dev/gps",
                lora_port="/dev/lora",
            )
            recorder.close()
            self.assertRegex(recorder.path.name, r"^mission_\d{8}_\d{6}\.rcm$")


if __name__ == "__main__":
    unittest.main()
