import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\//, "")).replace(/^([A-Z]:)/, (m) => m), "..");
const sandbox = { window: {}, console, Math, JSON, Number, Array, Set, Map, Object };
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root, "src/geometry.js"), "utf8"), sandbox, { filename: "geometry.js" });
vm.runInContext(fs.readFileSync(path.join(root, "src/model.js"), "utf8"), sandbox, { filename: "model.js" });
vm.runInContext(fs.readFileSync(path.join(root, "src/renderer.js"), "utf8"), sandbox, { filename: "renderer.js" });

const G = sandbox.window.RoadLogicModeler.geometry;
const east = G.cameraPoseFromPoints({ x: 100, y: 100 }, { x: 300, y: 100 }, 20);
assert.equal(east.direction, 0, "dragging east produces a zero-degree direction");
assert.equal(east.range, 200, "drag distance becomes camera range");

const north = G.cameraPoseFromPoints({ x: 100, y: 100 }, { x: 100, y: 20 }, 20);
assert.equal(north.direction, 270, "direction is normalized to 0-360 degrees");
assert.equal(north.range, 80);

const short = G.cameraPoseFromPoints({ x: 10, y: 10 }, { x: 11, y: 10 }, 20);
assert.equal(short.range, 20, "range respects the minimum handle distance");

const handle = G.cameraRangePoint({ x: 50, y: 60, direction: 90, range: 40 });
assert(Math.abs(handle.x - 50) < 1e-9);
assert(Math.abs(handle.y - 100) < 1e-9, "range handle lies on the camera direction ray");

const state = {
  selected: { type: "camera", id: "cam_1" },
  view: { x: 0, y: 0, zoom: 1 },
  model: G === sandbox.window.RoadLogicModeler.geometry ? sandbox.window.RoadLogicModeler.model.normalize({
    world: { width: 500, height: 500, gridSize: 20 },
    cameras: [{ id: "cam_1", x: 50, y: 60, direction: 90, range: 40 }]
  }) : null
};
const hit = sandbox.window.RoadLogicModeler.renderer.hitTest(state, { x: 50, y: 100 });
assert.equal(hit.type, "cameraHandle", "selected range endpoint is hit before the camera body");
assert.equal(hit.id, "cam_1");

const correspondence = sandbox.window.RoadLogicModeler.renderer.correspondenceBindings({
  model: { cameraCalibrations: [] }
}, {
  calibrationId: "missing_calibration",
  pointBindings: [{ imagePointId: "retained_binding", worldPoint: { x: 120, y: 180, height: 500 } }]
});
assert.equal(correspondence.length, 1, "a retained world marker stays renderable without its calibration point");
assert.equal(correspondence[0].label, "retained_binding");

const renderedLabels = [];
const fakeContext = {
  canvas: { width: 500, height: 500 },
  clearRect() {}, fillRect() {}, save() {}, restore() {}, setLineDash() {}, strokeRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, stroke() {}, arc() {}, closePath() {}, fill() {}, translate() {}, rotate() {}, roundRect() {},
  measureText(text) { return { width: String(text).length * 7 }; },
  fillText(text) { renderedLabels.push(String(text)); }
};
const renderState = {
  mode: "cameraPoint",
  showGrid: false,
  showNodes: true,
  showLabels: true,
  selected: { type: "camera", id: "cam_mark" },
  selectedImagePointId: "retained_binding",
  view: { x: 0, y: 0, zoom: 1 },
  model: sandbox.window.RoadLogicModeler.model.normalize({
    world: { width: 500, height: 500, gridSize: 20 },
    cameras: [{ id: "cam_mark", x: 50, y: 50, direction: 0, range: 60, calibrationId: "missing_calibration", pointBindings: [{ imagePointId: "retained_binding", worldPoint: { x: 120, y: 180, height: 500 } }] }]
  })
};
sandbox.window.RoadLogicModeler.renderer.render(fakeContext, renderState);
assert(renderedLabels.some((label) => label.includes("retained_binding")), "camera point mode draws a visible label for retained markers");

console.log("road_logic_modeler camera geometry tests passed");
