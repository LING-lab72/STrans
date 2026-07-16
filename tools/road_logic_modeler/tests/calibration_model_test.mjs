import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import assert from "node:assert/strict";

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\//, "")).replace(/^([A-Z]:)/, (m) => m), "..");
const sandbox = { window: {}, console, Math, JSON, Number, Array, Set, Map, Object };
sandbox.window = sandbox;
vm.createContext(sandbox);
for (const file of ["src/geometry.js", "src/model.js"]) {
  vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), sandbox, { filename: file });
}

const M = sandbox.window.RoadLogicModeler.model;
const model = M.normalize({
  world: { width: 400, height: 300, gridSize: 20 },
  cameras: [{
    id: "cam_1",
    image: { name: "legacy.jpg", dataUrl: "data:image/jpeg;base64,test", width: 640, height: 360 },
    imagePoints: [
      { id: "p1", x: 10, y: 20, target: { type: "grid_cell", cell: [3, 4] } },
      { id: "p1", x: 30, y: 40, target: { type: "world_point", point: { x: 100, y: 80 } } }
    ],
    imageLines: [{ id: "line", fromPointId: "p1", toPointId: "missing" }]
  }]
});

assert.equal(model.cameraCalibrations.length, 1, "legacy camera calibration is migrated into the shared library");
assert.equal(model.cameras[0].calibrationId, model.cameraCalibrations[0].id, "camera references migrated calibration");
assert.equal(model.cameraCalibrations[0].points.length, 2, "all legacy image points are retained");
assert.equal(new Set(model.cameraCalibrations[0].points.map((point) => point.id)).size, 2, "duplicate point ids are repaired");
assert.equal(model.cameraCalibrations[0].lines.length, 0, "lines with missing point references are removed");
assert.equal(model.cameras[0].pointBindings[0].gridCellId, "grid_3_4", "legacy grid target becomes an explicit point binding");

const payload = M.exportPayload(model);
assert.equal(payload.model.cameraCalibrations[0].image.dataUrl, undefined, "export keeps image metadata but excludes embedded base64 data");
assert.equal(model.cameraCalibrations[0].image.dataUrl, "data:image/jpeg;base64,test", "lightweight export does not remove the runtime preview image");
const cameraLogic = payload.logic.cameras[0];
assert.equal(cameraLogic.calibrationId, model.cameraCalibrations[0].id);
assert.equal(cameraLogic.pointBindings[0].imagePointId, "p1");
assert.deepEqual([...cameraLogic.pointBindings[0].gridCell], [3, 4]);
assert.equal(payload.model.cameras[0].image, undefined, "legacy embedded image is removed from camera instances");

const multiLaneCalibration = M.normalize({
  cameraCalibrations: [{
    id: "cal_1",
    points: [{ id: "a", x: 0, y: 0 }, { id: "b", x: 1, y: 1 }, { id: "c", x: 2, y: 2 }, { id: "d", x: 3, y: 3 }],
    lines: [
      { id: "lane", fromPointId: "a", toPointId: "b" },
      { id: "lane", fromPointId: "c", toPointId: "d" }
    ]
  }]
});
assert.equal(multiLaneCalibration.cameraCalibrations[0].lines.length, 2, "separate lane line segments are retained");
assert.equal(new Set(multiLaneCalibration.cameraCalibrations[0].lines.map((line) => line.id)).size, 2, "line ids are repaired when duplicated");

const lineCalibration = { id: "cal_toggle", points: [{ id: "a" }, { id: "b" }], lines: [] };
assert.equal(M.toggleCalibrationLine(lineCalibration, "a", "b"), true, "two image points can be connected");
assert.equal(lineCalibration.lines.length, 1);
assert.equal(M.toggleCalibrationLine(lineCalibration, "b", "a"), false, "connecting the same pair again removes it");
assert.equal(lineCalibration.lines.length, 0);
assert.equal(M.toggleCalibrationLine(lineCalibration, "a", "missing"), null, "unknown image points cannot create a line");

const targetModel = M.normalize({
  world: { width: 200, height: 120, gridSize: 20 },
  nodes: [{ id: "a", x: 10, y: 50 }, { id: "b", x: 190, y: 50 }],
  lanes: [{ id: "road", endpoint1: "a", endpoint2: "b", width: 20 }],
  buildings: [{ id: "shop", x: 100, y: 50, width: 40, height: 40 }],
  cameras: [], cameraCalibrations: []
});
const candidates = M.pointBindingCandidates(targetModel, { x: 100, y: 50 });
assert.deepEqual(Array.from(candidates, (item) => `${item.type}:${item.id}`).sort(), ["building:shop", "lane:road"], "overlapping road and building are both offered as explicit binding candidates");
const bindingModel = M.normalize({ cameras: [{ id: "cam", coverage: { gridCells: [] }, pointBindings: [{ imagePointId: "p", worldPoint: { x: 100, y: 50, height: 500 }, buildingId: "shop" }] }] });
assert.equal(bindingModel.cameras[0].pointBindings[0].buildingId, "shop");
assert.equal(bindingModel.cameras[0].pointBindings[0].worldPoint.x, 100, "explicit entity binding retains its world coordinate");

console.log("road_logic_modeler calibration model tests passed");
