import unittest
from unittest.mock import patch

from app.services.adaptive_scheduler import AdaptiveModelScheduler


def resources(*, cpu=20, memory=30, gpu_available=True, gpu=20, gpu_memory=30):
    return {
        "cpu": {"usage_percent": cpu},
        "memory": {"usage_percent": memory},
        "gpu": {
            "available": gpu_available,
            "usage_percent": gpu if gpu_available else None,
            "memory_usage_percent": gpu_memory if gpu_available else None,
        },
    }


class AdaptiveModelSchedulerTests(unittest.TestCase):
    def choose(self, snapshot, **overrides):
        scheduler = AdaptiveModelScheduler()
        arguments = {
            "camera_id": "test-camera",
            "task_mode": "vehicle_monitor",
            "requested_model": "auto",
            "confidence": 0.35,
            "inference_size": 640,
            "interval_ms": 100,
            "latest_inference_ms": 50,
            "is_static_image": False,
        }
        arguments.update(overrides)
        with patch("app.services.adaptive_scheduler.system_monitor.snapshot", return_value=snapshot):
            return scheduler.choose(**arguments)

    def test_static_image_selects_quality_profile_and_larger_input(self):
        decision = self.choose(resources(), is_static_image=True)

        self.assertEqual(decision["profile"], "quality")
        self.assertGreaterEqual(decision["inference_size"], 960)
        self.assertGreaterEqual(decision["detection_interval_ms"], 400)

    def test_road_anomaly_preserves_small_target_resolution(self):
        decision = self.choose(resources(), task_mode="road_anomaly", inference_size=640)

        self.assertEqual(decision["profile"], "anomaly")
        self.assertGreaterEqual(decision["inference_size"], 768)
        self.assertLessEqual(decision["confidence"], 0.25)

    def test_resource_pressure_selects_protect_profile_and_fallback_model(self):
        decision = self.choose(resources(memory=95))

        self.assertEqual(decision["profile"], "protect")
        self.assertEqual(decision["model_name"], "fallback")
        self.assertLessEqual(decision["inference_size"], 512)
        self.assertGreaterEqual(decision["detection_interval_ms"], 350)

    def test_slow_inference_selects_realtime_profile(self):
        decision = self.choose(resources(gpu=80), latest_inference_ms=160)

        self.assertEqual(decision["profile"], "realtime")
        self.assertLessEqual(decision["inference_size"], 640)
        self.assertGreaterEqual(decision["detection_interval_ms"], 180)

    def test_available_idle_gpu_selects_quality_profile(self):
        decision = self.choose(resources(gpu=30, gpu_memory=40), latest_inference_ms=80)

        self.assertEqual(decision["profile"], "quality")
        self.assertGreaterEqual(decision["inference_size"], 768)

    def test_disabled_scheduler_preserves_manual_configuration(self):
        scheduler = AdaptiveModelScheduler()
        scheduler.configure(False)

        with patch("app.services.adaptive_scheduler.system_monitor.snapshot", return_value=resources(memory=99)):
            decision = scheduler.choose("camera", "vehicle_monitor", "auto", 0.4, 800, 120)

        self.assertEqual(decision["profile"], "manual")
        self.assertEqual(decision["model_name"], "auto")
        self.assertEqual(decision["inference_size"], 800)
        self.assertEqual(decision["detection_interval_ms"], 120)


if __name__ == "__main__":
    unittest.main()
