import tempfile
import unittest
from pathlib import Path

from app.schemas.video import CameraCreateRequest, CameraUpdateRequest
from app.services.camera_hub import CameraHub


class CameraHubPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "cameras.db"
        self.hub = CameraHub(self.database_path)

    def tearDown(self):
        self.hub.stop_all()
        self.temporary_directory.cleanup()

    def test_custom_camera_is_persisted_and_reloaded(self):
        created = self.hub.add_source(
            CameraCreateRequest(
                name="测试视频",
                type="custom",
                stream_url="sample.mp4",
                location="测试区域",
                heatmap_mode="frame",
            )
        )

        reloaded = CameraHub(self.database_path)
        try:
            source = reloaded.get_source(created.camera_id)
            self.assertEqual(source.name, "测试视频")
            self.assertEqual(source.stream_url, "sample.mp4")
            self.assertEqual(source.heatmap_mode, "frame")
        finally:
            reloaded.stop_all()

    def test_update_changes_persisted_fields_and_delete_removes_custom_camera(self):
        created = self.hub.add_source(
            CameraCreateRequest(
                name="旧名称",
                type="custom",
                stream_url="old.mp4",
                location="旧位置",
            )
        )

        updated = self.hub.update_source(
            created.camera_id,
            CameraUpdateRequest(name="新名称", stream_url="new.mp4", heatmap_mode="off"),
        )
        self.assertEqual(updated.name, "新名称")
        self.assertEqual(updated.stream_url, "new.mp4")
        self.assertEqual(updated.heatmap_mode, "off")

        self.hub.delete_source(created.camera_id)
        with self.assertRaises(KeyError):
            self.hub.get_source(created.camera_id)

    def test_preset_camera_cannot_be_deleted(self):
        with self.assertRaisesRegex(ValueError, "预置沙盘摄像头不能删除"):
            self.hub.delete_source("live1")

    def test_schema_only_accepts_current_camera_types(self):
        camera_type_schema = CameraCreateRequest.model_json_schema()["properties"]["type"]
        self.assertEqual(
            set(camera_type_schema["enum"]),
            {"sandtable", "phone", "usb", "custom"},
        )


if __name__ == "__main__":
    unittest.main()
