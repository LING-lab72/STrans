import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const modelerRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "public", "road_logic_modeler");

function loadModeler(...files) {
  const sandbox = { window: {}, console, Math, JSON, Number, Array, Set, Map, Object };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  for (const file of files) {
    vm.runInContext(readFileSync(resolve(modelerRoot, file), "utf8"), sandbox, { filename: file });
  }
  return sandbox.window.RoadLogicModeler;
}

test("vendored road modeler creates connected lane groups and exports its schema", () => {
  const { model: modelApi } = loadModeler("src/geometry.js", "src/model.js");
  const model = modelApi.createModel();
  const sectionA = modelApi.createNodeGroup(model, { x: 100, y: 100 }, { count: 2, spacing: 30, angle: 90 });
  const sectionB = modelApi.createNodeGroup(model, { x: 300, y: 100 }, { count: 2, spacing: 30, angle: 90 });
  const lanes = modelApi.connectNodeGroups(model, sectionA.id, sectionB.id);
  const payload = modelApi.exportPayload(model);

  assert.equal(lanes.length, 2);
  assert.equal(payload.schema, "road_logic_modeler.v1");
  assert.equal(payload.model.lanes.length, 2);
  assert.ok(payload.logic.lanes.length >= 2);
});

test("vendored road modeler derives camera direction and range", () => {
  const { geometry } = loadModeler("src/geometry.js");
  const pose = geometry.cameraPoseFromPoints({ x: 100, y: 100 }, { x: 300, y: 100 }, 20);

  assert.equal(pose.direction, 0);
  assert.equal(pose.range, 200);
});
