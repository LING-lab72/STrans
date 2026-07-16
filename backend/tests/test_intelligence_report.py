import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.HTTPError = RuntimeError
    httpx_stub.post = None
    sys.modules["httpx"] = httpx_stub

from app.services.intelligence_report import IntelligenceReportService


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "# 测试交通报告\n运行状态正常。"}}]}


class IntelligenceReportServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.service = IntelligenceReportService(Path(self.temporary_directory.name) / "reports.db")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_update_config_masks_api_key_and_preserves_it_when_omitted(self):
        configured = self.service.update_config("https://example.test/v1/", "test-model", "secret-key")
        updated = self.service.update_config("https://example.test/v2", "next-model", None)

        self.assertTrue(configured["configured"])
        self.assertTrue(configured["api_key_masked"].endswith("-key"))
        self.assertEqual(updated["model"], "next-model")
        self.assertTrue(updated["configured"])

    def test_invalid_api_base_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "http"):
            self.service.update_config("ftp://example.test", "test-model", "secret")

    def test_generate_requires_an_api_key(self):
        with self.assertRaisesRegex(ValueError, "API Key"):
            self.service.generate({"camera_id": "camera"}, "admin")

    def test_generated_report_is_persisted_listed_and_deleted(self):
        self.service.update_config("https://example.test/v1", "test-model", "secret-key")
        context = {"camera_id": "camera", "camera_name": "测试视角", "vehicle_count": 2}

        with patch("app.services.intelligence_report.httpx.post", return_value=FakeResponse()):
            report = self.service.generate(context, "admin")

        listed = self.service.list_reports()
        self.assertEqual(report["title"], "测试视角交通智能分析报告")
        self.assertEqual(listed[0]["input_summary"]["vehicle_count"], 2)
        self.assertTrue(self.service.delete_report(report["id"]))
        self.assertEqual(self.service.list_reports(), [])


if __name__ == "__main__":
    unittest.main()
