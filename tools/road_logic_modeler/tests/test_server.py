import importlib.util
from pathlib import Path

import pytest


SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("road_logic_modeler_server", SERVER_PATH)
SERVER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SERVER)


@pytest.mark.parametrize("url", ["rtsp://127.0.0.1/live", "rtsps://camera.example/live"])
def test_validate_rtsp_url_accepts_supported_schemes(url):
    assert SERVER.validate_rtsp_url(url) == url


@pytest.mark.parametrize("url", ["", "http://camera.example/live", "rtsp:///missing-host"])
def test_validate_rtsp_url_rejects_invalid_sources(url):
    with pytest.raises(ValueError):
        SERVER.validate_rtsp_url(url)


def test_static_root_points_to_the_vendored_modeler_page():
    assert (SERVER.STATIC_ROOT / "index.html").is_file()
    assert SERVER.STATIC_ROOT.name == "road_logic_modeler"
