import tempfile
import unittest
import sys
import types
from pathlib import Path
from unittest.mock import patch

try:
    import ultralytics  # noqa: F401
except ModuleNotFoundError:
    ultralytics_stub = types.ModuleType("ultralytics")
    ultralytics_stub.YOLO = object
    ultralytics_utils_stub = types.ModuleType("ultralytics.utils")
    ultralytics_downloads_stub = types.ModuleType("ultralytics.utils.downloads")
    ultralytics_downloads_stub.attempt_download_asset = lambda name: name
    ultralytics_stub.utils = ultralytics_utils_stub
    ultralytics_utils_stub.downloads = ultralytics_downloads_stub
    sys.modules["ultralytics"] = ultralytics_stub
    sys.modules["ultralytics.utils"] = ultralytics_utils_stub
    sys.modules["ultralytics.utils.downloads"] = ultralytics_downloads_stub

from app.services import local_model


class LocalModelDownloadTests(unittest.TestCase):
    def test_missing_primary_model_is_downloaded_into_backend_data(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            target = root / "data" / "yolo11s.pt"
            fallback = root / "data" / "yolov11s-visdrone.pt"
            downloaded = root / "downloads" / "yolo11s.pt"
            downloaded.parent.mkdir()
            downloaded.write_bytes(b"model-weights")

            with patch.object(local_model, "AUTO_MODEL", target), \
                 patch.object(local_model, "VISDRONE_MODEL", fallback), \
                 patch.object(local_model, "attempt_download_asset", return_value=str(downloaded)) as download:
                resolved = local_model.ensure_auto_model()

            self.assertEqual(resolved, target)
            self.assertEqual(target.read_bytes(), b"model-weights")
            download.assert_called_once_with("yolo11s.pt")


if __name__ == "__main__":
    unittest.main()
