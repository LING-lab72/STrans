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

const M = sandbox.window.RoadLogicModeler.model;
assert.equal(M.CAMERA_PRESETS.length, 12, "sandbox guide exposes all twelve RTSP stream presets");
assert.equal(M.CAMERA_PRESETS[0].url, "rtsp://10.126.59.120:8554/live/live1");
assert.equal(M.CAMERA_PRESETS[11].place, "道路1");
const model = M.normalize({
  name: "test",
  world: { width: 400, height: 300, gridSize: 20, unit: "cm" },
  nodes: [
    { id: "n1", name: "A", type: "junction", x: 100, y: 100, z: 2 },
    { id: "n2", name: "B", type: "boundary", x: 300, y: 100, z: 4 },
    { id: "n3", name: "C", type: "lane_point", x: 200, y: 160, z: 3 }
  ],
  lanes: [
    { id: "l1", name: "主车道", endpoint1: "n1", endpoint2: "n2", direction: "1-2", height: null },
    { id: "l2", name: "分叉", endpoint1: "n1", endpoint2: "n3", direction: "1-2", controlPoints: [[130, 130]] }
  ],
  laneEndpointGroups: [{ id: "g1", name: "汇流组", nodeIds: ["n2", "n3"], order: "auto" }],
  buildings: [],
  cameras: [{
    id: "cam1",
    name: "相机",
    x: 120,
    y: 60,
    coverage: { gridCells: [[9, 5], [10, 5]] },
    image: { name: "frame.png", dataUrl: "data:image/png;base64,test", width: 640, height: 360 },
    imagePoints: [
      { id: "imgpt_1", name: "画面点 1", x: 120, y: 80, target: { type: "node", nodeId: "n1" } },
      { id: "imgpt_2", name: "画面点 2", x: 240, y: 80, target: { type: "lane", laneId: "l1" } }
    ],
    imageLines: [{ id: "imgline_1", fromPointId: "imgpt_1", toPointId: "imgpt_2" }]
  }]
});

const logic = M.buildLogic(model);
const l1 = logic.lanes.find((lane) => lane.id === "l1");
assert.equal(l1.height, 3, "lane height defaults to endpoint z average");

const n1 = logic.nodes.find((node) => node.id === "n1");
assert.deepEqual([...n1.sides.east], ["l1"], "junction classifies eastbound lane by side");
assert.deepEqual([...n1.sides.south], ["l2"], "junction classifies southeast turn by nearest side");

const group = logic.laneEndpointGroups.find((item) => item.id === "g1");
assert.deepEqual(group.mergeLaneIds.sort(), ["l1", "l2"], "group lists lanes connected through grouped endpoints");

const splitModel = M.normalize({
  nodes: [
    { id: "source", x: 0, y: 50 },
    { id: "fork_in", type: "lane_point", x: 50, y: 50 },
    { id: "fork_left", type: "lane_point", x: 60, y: 40 },
    { id: "fork_right", type: "lane_point", x: 60, y: 60 },
    { id: "left", x: 100, y: 20 },
    { id: "right", x: 100, y: 80 }
  ],
  lanes: [
    { id: "trunk", endpoint1: "source", endpoint2: "fork_in", direction: "1-2" },
    { id: "branch_left", endpoint1: "fork_left", endpoint2: "left", direction: "1-2" },
    { id: "branch_right", endpoint1: "fork_right", endpoint2: "right", direction: "1-2" }
  ],
  laneEndpointGroups: [
    { id: "fork", name: "主路分流", kind: "auto", nodeIds: ["fork_in", "fork_left", "fork_right"] },
    { id: "stale", nodeIds: ["fork_in", "missing"] }
  ]
});

assert.deepEqual([...splitModel.laneEndpointGroups[1].nodeIds], [], "a road node belongs to only one node group");

const placementModel = M.createModel();
const sectionA = M.createNodeGroup(placementModel, { x: 100, y: 100 }, { count: 3, spacing: 30, angle: 90 });
const sectionB = M.createNodeGroup(placementModel, { x: 300, y: 120 }, { count: 3, spacing: 30, angle: 90 });
assert.deepEqual(Array.from(sectionA.nodeIds, (id) => {
  const node = M.nodeById(placementModel, id);
  return [node.x, node.y];
}), [[100, 70], [100, 100], [100, 130]], "placing a node group creates parallel offset road nodes");

M.moveNodeGroup(placementModel, sectionA.id, { x: 140, y: 160 });
assert.deepEqual(Array.from(sectionA.nodeIds, (id) => {
  const node = M.nodeById(placementModel, id);
  return [node.x, node.y];
}), [[140, 130], [140, 160], [140, 190]], "dragging a node group preserves member offsets");

const generatedLanes = M.connectNodeGroups(placementModel, sectionA.id, sectionB.id);
assert.equal(generatedLanes.length, 3, "group-to-group road association creates one lane per paired node");
assert.deepEqual(Array.from(generatedLanes, (lane) => [lane.endpoint1, lane.endpoint2]), Array.from(sectionA.nodeIds, (id, index) => [id, sectionB.nodeIds[index]]));

M.deleteNodeGroup(placementModel, sectionA.id);
assert.equal(placementModel.laneEndpointGroups.some((group) => group.id === sectionA.id), false);
assert.equal(sectionA.nodeIds.some((id) => M.nodeById(placementModel, id)), false, "deleting a generated group removes its road nodes");
assert.equal(placementModel.lanes.length, 0, "deleting a group removes lanes attached to its road nodes");

const conversionModel = M.normalize({
  nodes: [
    { id: "port", type: "junction", x: 100, y: 100 },
    { id: "far", type: "junction", x: 300, y: 100 }
  ],
  lanes: [
    { id: "parallel_1", endpoint1: "port", endpoint2: "far", width: 28, renderOrder: 0 },
    { id: "parallel_2", endpoint1: "port", endpoint2: "far", width: 28, renderOrder: 1 }
  ],
  laneEndpointGroups: []
});
const converted = M.convertNodeToGroup(conversionModel, "port");
assert.equal(converted.nodeIds.length, 2, "each lane connection becomes one road-internal node");
assert.equal(M.nodeById(conversionModel, "port"), undefined, "the temporary junction port is removed after conversion");
assert.deepEqual(Array.from(converted.nodeIds, (id) => M.nodeById(conversionModel, id).y), [86, 114], "converted nodes preserve parallel lane offsets");
assert.deepEqual(Array.from(conversionModel.lanes, (lane) => lane.endpoint1), Array.from(converted.nodeIds), "lanes reconnect to their own road-internal nodes");
const convertedFar = M.convertNodeToGroup(conversionModel, "far");
assert.deepEqual(Array.from(conversionModel.lanes, (lane) => [
  M.nodeById(conversionModel, lane.endpoint1).y,
  M.nodeById(conversionModel, lane.endpoint2).y
]), [[86, 86], [114, 114]], "converting both road ports keeps parallel lanes from crossing");
assert.equal(M.laneBundleKey(conversionModel, conversionModel.lanes[0]), M.laneBundleKey(conversionModel, conversionModel.lanes[1]), "lanes sharing endpoint groups are recognized as one parallel bundle");

const cam = logic.cameras.find((item) => item.id === "cam1");
assert(cam.observedLaneIds.includes("l1"), "camera coverage grid maps to nearby lane");
const calibration = logic.cameraCalibrations.find((item) => item.id === cam.calibrationId);
assert.equal(calibration.image.name, "frame.png", "camera image metadata is exported in shared calibration");
assert.equal(calibration.points.length, 2, "camera image points are exported in shared calibration");
assert.equal(calibration.lines[0].fromPointId, "imgpt_1", "camera image lines are exported in shared calibration");
assert.equal(cam.pointBindings.length, 2, "legacy point targets migrate to camera bindings");

const payload = M.exportPayload(model);
assert.equal(payload.schema, "road_logic_modeler.v1");
assert(payload.model && payload.logic, "export includes editable model and derived logic");
assert.equal(payload.model.cameraCalibrations[0].image.dataUrl, undefined, "exported JSON excludes embedded preview image data");
assert.equal(payload.model.cameras[0].imageTargetType, undefined, "export strips camera UI-only target type");

console.log("road_logic_modeler model logic tests passed");
