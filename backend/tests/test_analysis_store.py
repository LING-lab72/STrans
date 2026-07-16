import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.schemas.dashboard import AnalysisResult, DetectionBox, TrafficEvent, TrafficStats
from app.services.analysis_store import AnalysisStore


class AnalysisStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = AnalysisStore(Path(self.temporary_directory.name) / "analysis.db")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def result(self):
        return AnalysisResult(
            frame_id=7,
            timestamp="2026-07-14T12:00:00",
            camera_id="test-camera",
            model_id="test-model",
            inference_ms=12.5,
            detections=[
                DetectionBox(
                    bbox=[10, 20, 60, 80],
                    class_name="car",
                    confidence=0.9,
                    plate="京A12345",
                    whitelist_status=True,
                    gate_action="allow",
                ),
                DetectionBox(
                    bbox=[70, 20, 120, 80],
                    class_name="car",
                    confidence=0.8,
                    plate="京Z99999",
                    whitelist_status=False,
                    gate_action="deny",
                ),
            ],
            traffic_stats=TrafficStats(
                vehicle_count=2,
                current_count=2,
                density=0.25,
                avg_speed=8.5,
                congestion_level="low",
            ),
            events=[
                TrafficEvent(
                    event_id="evt_test",
                    type="road_obstacle",
                    severity="warning",
                    description="测试异常",
                    camera_id="test-camera",
                    bbox=[20, 30, 40, 50],
                )
            ],
        )

    def test_save_persists_counts_plates_and_camera_filter(self):
        record_id = self.store.save(self.result())

        records = self.store.list_records(camera_id="test-camera")
        self.assertEqual(records[0]["id"], record_id)
        self.assertEqual(records[0]["vehicle_count"], 2)
        self.assertEqual(records[0]["plates"], "京A12345,京Z99999")
        self.assertEqual(records[0]["whitelist_pass_count"], 1)
        self.assertEqual(records[0]["whitelist_block_count"], 1)
        self.assertEqual(self.store.count_records(camera_id="other-camera"), 0)

    def test_incident_evidence_round_trips_image_analysis_and_hash(self):
        image = b"test-jpeg-bytes"
        self.store.save(self.result(), source_jpeg=image)

        evidence = self.store.get_incident_evidence("evt_test")

        self.assertEqual(evidence["image"], image)
        self.assertEqual(evidence["image_sha256"], hashlib.sha256(image).hexdigest())
        self.assertEqual(evidence["analysis"]["camera_id"], "test-camera")
        self.assertEqual(evidence["incident"]["status"], "pending")

    def test_incident_status_and_exports_reflect_persisted_state(self):
        self.store.save(self.result())

        incident = self.store.update_incident("evt_test", "resolved", "tester", "已复核")
        csv_export = self.store.export_csv()
        json_export = json.loads(self.store.export_json())

        self.assertEqual(incident["status"], "resolved")
        self.assertEqual(incident["handled_by"], "tester")
        self.assertIn("test-camera", csv_export)
        self.assertEqual(json_export["items"][0]["camera_id"], "test-camera")

    def test_invalid_or_missing_incident_updates_are_rejected(self):
        self.store.save(self.result())

        with self.assertRaisesRegex(ValueError, "无效的告警状态"):
            self.store.update_incident("evt_test", "invalid", "tester")
        with self.assertRaisesRegex(ValueError, "告警记录不存在"):
            self.store.update_incident("missing", "resolved", "tester")


if __name__ == "__main__":
    unittest.main()
