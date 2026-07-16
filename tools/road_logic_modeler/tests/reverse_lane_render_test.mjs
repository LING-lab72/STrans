import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\//, "")).replace(/^([A-Z]:)/, (m) => m), "..");

function load(file, sandbox) {
  vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), sandbox, { filename: file });
}

const sandbox = { window: {}, console, Math, JSON, Number, Array, Set, Object };
sandbox.window = sandbox;
vm.createContext(sandbox);
load("src/geometry.js", sandbox);
load("src/model.js", sandbox);
load("src/renderer.js", sandbox);

const M = sandbox.window.RoadLogicModeler.model;
const R = sandbox.window.RoadLogicModeler.renderer;

const model = M.normalize({
  world: { width: 500, height: 300, gridSize: 20, unit: "cm" },
  nodes: [
    { id: "a", name: "A", type: "junction", x: 100, y: 120, z: 0 },
    { id: "b", name: "B", type: "junction", x: 300, y: 120, z: 0 }
  ],
  lanes: [
    { id: "ab", name: "A到B", endpoint1: "a", endpoint2: "b", width: 28, renderOrder: 0 },
    { id: "ba", name: "B到A", endpoint1: "b", endpoint2: "a", width: 28, renderOrder: 1 }
  ]
});

const state = {
  model,
  view: { x: 0, y: 0, zoom: 1 },
  selected: null,
  showGrid: false,
  showNodes: true,
  showLabels: true
};

const ab = model.lanes.find((lane) => lane.id === "ab");
const ba = model.lanes.find((lane) => lane.id === "ba");
const abPath = R.laneScreenPath(state, ab, "a");
const baPath = R.laneScreenPath(state, ba, "a");

assert.deepEqual({ ...abPath[0] }, { x: 100, y: 120 }, "forward lane starts at canonical endpoint");
assert.deepEqual({ ...baPath[0] }, { x: 100, y: 120 }, "reverse lane is rendered in canonical bundle direction");
assert.deepEqual({ ...abPath.at(-1) }, { x: 300, y: 120 }, "forward lane ends at the other endpoint");
assert.deepEqual({ ...baPath.at(-1) }, { x: 300, y: 120 }, "reverse lane ends at the other endpoint after canonicalization");

const width = 28;
const left = sandbox.window.RoadLogicModeler.geometry.offsetPolyline(abPath, -width / 2);
const right = sandbox.window.RoadLogicModeler.geometry.offsetPolyline(baPath, width / 2);
assert.notEqual(left[0].y, right[0].y, "opposite directions in one bundle offset to different sides");

const groupedModel = M.normalize({
  nodes: [
    { id: "junction", type: "junction", x: 100, y: 100 },
    { id: "g1", type: "lane_point", x: 300, y: 86 },
    { id: "g2", type: "lane_point", x: 300, y: 114 }
  ],
  lanes: [
    { id: "p1", endpoint1: "junction", endpoint2: "g1", width: 28, renderOrder: 0 },
    { id: "p2", endpoint1: "junction", endpoint2: "g2", width: 28, renderOrder: 1 }
  ],
  laneEndpointGroups: [{ id: "section", nodeIds: ["g1", "g2"], order: "manual" }]
});
const groupedState = { ...state, model: groupedModel };
const bundleStart = "node:junction";
const p1Base = R.laneScreenPath(groupedState, groupedModel.lanes[0], bundleStart, true);
const p2Base = R.laneScreenPath(groupedState, groupedModel.lanes[1], bundleStart, true);
assert.deepEqual(Array.from(p1Base, (point) => ({ ...point })), Array.from(p2Base, (point) => ({ ...point })), "grouped lane members share one logical center path before offset rendering");
const p1Rendered = sandbox.window.RoadLogicModeler.geometry.offsetPolyline(p1Base, -14);
const p2Rendered = sandbox.window.RoadLogicModeler.geometry.offsetPolyline(p2Base, 14);
assert.deepEqual([p1Rendered[0].y, p2Rendered[0].y], [86, 114], "shared junction port expands into parallel lane endpoints");

const selectableModel = M.normalize({
  nodes: [
    { id: "top", type: "lane_point", x: 100, y: 72 },
    { id: "center", type: "lane_point", x: 100, y: 100 },
    { id: "bottom", type: "lane_point", x: 100, y: 128 }
  ],
  lanes: [],
  laneEndpointGroups: [{ id: "three_lane_section", nodeIds: ["top", "center", "bottom"], order: "manual" }],
  buildings: [], cameras: [], cameraCalibrations: []
});
const selectableState = { ...state, model: selectableModel };
assert.deepEqual({ ...R.hitTest(selectableState, { x: 100, y: 100 }) }, { type: "node", id: "center" }, "the center road node must win hit testing over its node group");

console.log("reverse lane render regression test passed");
