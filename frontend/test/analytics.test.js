import test from "node:test";
import assert from "node:assert/strict";

import { buildTrendChart } from "../src/analytics.js";


test("trend chart summarizes the newest records in chronological order", () => {
  const records = [
    { id: 3, camera_id: "live2", vehicle_count: 5 },
    { id: 2, camera_id: "live1", vehicle_count: 3 },
    { id: 1, camera_id: "live1", vehicle_count: 1 },
  ];

  const chart = buildTrendChart(records, "vehicle_count", 2);

  assert.deepEqual(chart.points.map((point) => point.item.id), [2, 3]);
  assert.deepEqual(chart.summary, { total: 8, average: 4, peak: 5, latest: 5 });
  assert.deepEqual(chart.cameraDistribution.map(({ name, value }) => [name, value]), [
    ["live2", 5],
    ["live1", 3],
  ]);
});

test("trend chart clamps invalid and negative values to zero", () => {
  const records = [
    { id: 2, camera_id: "live1", event_count: -2 },
    { id: 1, camera_id: "live1", event_count: "not-a-number" },
  ];

  const chart = buildTrendChart(records, "event_count", 20);

  assert.deepEqual(chart.points.map((point) => point.value), [0, 0]);
  assert.equal(chart.maxValue, 1);
  assert.equal(chart.areaPath.startsWith("M "), true);
});
