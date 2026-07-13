import test from "node:test";
import assert from "node:assert/strict";

import { frameHeatmapSpots, resolveHeatmapMode } from "../src/heatmap.js";

test("mobile cameras default to frame heatmap while sandtable cameras stay road mapped", () => {
  assert.equal(resolveHeatmapMode({ type: "phone", heatmap_mode: "auto" }), "frame");
  assert.equal(resolveHeatmapMode({ type: "sandtable", heatmap_mode: "auto" }), "road");
  assert.equal(resolveHeatmapMode({ type: "phone", heatmap_mode: "road" }), "road");
  assert.equal(resolveHeatmapMode({ type: "phone", heatmap_mode: "off" }), "off");
});

test("frame heatmap converts detection boxes into percentage-based centers", () => {
  const spots = frameHeatmapSpots({
    camera_id: "phone1",
    source_width: 1920,
    source_height: 1080,
    detections: [
      { camera_id: "phone1", bbox: [480, 270, 960, 810], confidence: 0.9, class_name: "car" },
      { camera_id: "other", bbox: [0, 0, 100, 100], confidence: 0.9, class_name: "car" },
    ],
  }, "phone1");

  assert.deepEqual(spots, [{ x: 37.5, y: 50, strength: 0.9, size: 29 }]);
});

test("frame heatmap caps rendered hotspots to protect the live video view", () => {
  const detections = Array.from({ length: 81 }, (_, index) => ({
    bbox: [index, 0, index + 1, 1], confidence: 0.5, class_name: "car",
  }));

  assert.equal(frameHeatmapSpots({ source_width: 100, source_height: 100, detections }, "phone1").length, 80);
});
