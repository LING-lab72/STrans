import test from "node:test";
import assert from "node:assert/strict";

import { CAMERA_TYPE_OPTIONS, monitorCameraOptions } from "../src/cameraTypes.js";


test("camera creation only offers currently supported acquisition types", () => {
  assert.deepEqual(
    CAMERA_TYPE_OPTIONS,
    [
      { value: "custom", label: "自定义" },
      { value: "phone", label: "手机" },
      { value: "usb", label: "USB 摄像头" },
      { value: "sandtable", label: "沙盘 RTSP" },
    ],
  );
});

test("realtime monitor keeps custom cameras beyond the twelve presets", () => {
  const cameras = Array.from({ length: 12 }, (_, index) => ({ camera_id: `live${index + 1}` }));
  cameras.push({ camera_id: "custom1", name: "真实沙盘录像" });

  assert.deepEqual(
    monitorCameraOptions(cameras).map((camera) => camera.camera_id),
    [...Array.from({ length: 12 }, (_, index) => `live${index + 1}`), "custom1"],
  );
});
