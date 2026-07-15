import assert from "node:assert/strict";
import * as M from "../src/flow_matcher_model.js";

const assignment = {
  id: "road_a->road_b",
  nodeId: "node_1",
  incomingLaneIds: ["in_1", "in_2"],
  outgoingLaneIds: ["out_1", "out_2", "out_3"],
  laneAssignments: [],
};

assert.equal(M.toggleLaneMatch(assignment, "in_1", "out_1"), true);
assert.deepEqual(assignment.laneAssignments, [{ fromLaneId: "in_1", toLaneId: "out_1" }]);
assert.equal(M.toggleLaneMatch(assignment, "in_1", "out_2"), true);
assert.equal(assignment.laneAssignments.length, 2, "split mappings must allow one incoming lane to have multiple exits");
assert.equal(M.toggleLaneMatch(assignment, "in_2", "out_1"), true);
assert.equal(assignment.laneAssignments.length, 3, "merge mappings must allow multiple incoming lanes to share one exit");
assert.equal(M.toggleLaneMatch(assignment, "in_1", "out_1"), false);
assert.equal(assignment.laneAssignments.some((item) => item.fromLaneId === "in_1" && item.toLaneId === "out_1"), false);
assert.throws(() => M.toggleLaneMatch(assignment, "unknown", "out_1"), /Unknown incoming lane/);

assert.deepEqual(
  M.suggestOrderedMatches({ incomingLaneIds: ["i1", "i2", "i3"], outgoingLaneIds: ["o1", "o2"] }),
  [
    { fromLaneId: "i1", toLaneId: "o1" },
    { fromLaneId: "i2", toLaneId: "o2" },
    { fromLaneId: "i3", toLaneId: "o2" },
  ],
  "merge suggestions must preserve lateral order",
);
assert.deepEqual(
  M.suggestOrderedMatches({ incomingLaneIds: ["i1", "i2"], outgoingLaneIds: ["o1", "o2", "o3"] }),
  [
    { fromLaneId: "i1", toLaneId: "o1" },
    { fromLaneId: "i2", toLaneId: "o2" },
    { fromLaneId: "i2", toLaneId: "o3" },
  ],
  "split suggestions must preserve lateral order",
);

const exported = M.buildConfirmedExport({ schema: "template", nodes: [{ nodeId: "node_1", roadBundleAssignments: [assignment] }] });
assert.equal(exported.schema, "road_logic_modeler.confirmed-node-flow.v1");
assert.equal(exported.nodes[0].roadBundleAssignments[0].status, "confirmed");
assert.equal(exported.nodes[0].roadBundleAssignments[0].laneAssignments.length, 2);

const directionTemplate = {
  schema: "template",
  nodes: [
    { nodeId: "a", assignmentPolicy: "manual_road_bundle_mapping", trunkRoadBundleIds: ["road"], arms: [{ roadBundleId: "road", laneIds: ["lane"], incomingLaneIds: [], outgoingLaneIds: ["lane"] }], roadBundleAssignments: [] },
    { nodeId: "b", assignmentPolicy: "manual_road_bundle_mapping", trunkRoadBundleIds: ["road"], arms: [{ roadBundleId: "road", laneIds: ["lane"], incomingLaneIds: ["lane"], outgoingLaneIds: [] }], roadBundleAssignments: [] },
  ],
};
const directionRoad = { lanes: [{ id: "lane", traffic: { sourceNodeId: "a", targetNodeId: "b" } }] };
M.rebuildDirections(directionTemplate, directionRoad, new Set(["lane"]));
assert.deepEqual(directionTemplate.nodes[0].arms[0].incomingLaneIds, ["lane"]);
assert.deepEqual(directionTemplate.nodes[1].arms[0].outgoingLaneIds, ["lane"]);
const overrideExport = M.buildConfirmedExport(directionTemplate, directionRoad, new Set(["lane"]));
assert.deepEqual(overrideExport.laneDirectionOverrides[0], { laneId: "lane", originalSourceNodeId: "a", originalTargetNodeId: "b", sourceNodeId: "b", targetNodeId: "a" });

const solverTemplate = {
  nodes: [{
    nodeId: "junction",
    assignmentPolicy: "manual_road_bundle_mapping",
    arms: [
      { roadBundleId: "west", angleDegrees: 180, laneIds: ["w1", "w2", "w3", "w4"], incomingLaneIds: ["w1", "w2"], outgoingLaneIds: ["w3", "w4"] },
      { roadBundleId: "east", angleDegrees: 0, laneIds: ["e1", "e2", "e3", "e4"], incomingLaneIds: ["e1", "e2"], outgoingLaneIds: ["e3", "e4"] },
      { roadBundleId: "access", angleDegrees: 90, laneIds: ["a1", "a2"], incomingLaneIds: ["a1"], outgoingLaneIds: ["a2"] },
    ],
    trunkRoadBundleIds: ["west", "east"],
    roadBundleAssignments: [
      { id: "west->east", fromRoadBundleId: "west", toRoadBundleId: "east", incomingLaneIds: ["w1", "w2"], outgoingLaneIds: ["e3", "e4"], laneAssignments: [] },
      { id: "east->west", fromRoadBundleId: "east", toRoadBundleId: "west", incomingLaneIds: ["e1", "e2"], outgoingLaneIds: ["w3", "w4"], laneAssignments: [] },
      { id: "west->access", fromRoadBundleId: "west", toRoadBundleId: "access", incomingLaneIds: ["w1", "w2"], outgoingLaneIds: ["a2"], laneAssignments: [] },
      { id: "east->access", fromRoadBundleId: "east", toRoadBundleId: "access", incomingLaneIds: ["e1", "e2"], outgoingLaneIds: ["a2"], laneAssignments: [] },
      { id: "access->west", fromRoadBundleId: "access", toRoadBundleId: "west", incomingLaneIds: ["a1"], outgoingLaneIds: ["w3", "w4"], laneAssignments: [] },
      { id: "access->east", fromRoadBundleId: "access", toRoadBundleId: "east", incomingLaneIds: ["a1"], outgoingLaneIds: ["e3", "e4"], laneAssignments: [] },
    ],
  }],
};
const solveReport = M.applyDeterministicMatches(solverTemplate);
assert.equal(solveReport.autoAddedMatchCount, 6, "two trunk continuations and two access movements should be completed");
assert.equal(solverTemplate.nodes[0].roadBundleAssignments.filter((item) => item.laneAssignments.length).length, 4);
assert.deepEqual(solverTemplate.nodes[0].roadBundleAssignments[0].laneAssignments, [{ fromLaneId: "w1", toLaneId: "e4" }, { fromLaneId: "w2", toLaneId: "e3" }]);
const validation = M.analyzeFlowMatching(solverTemplate);
assert.equal(validation.conflictCount, 0);
assert.equal(validation.uncoveredLanePortCount, 0);
assert.equal(validation.nodes[0].freedomCount, 0);

const invalidTemplate = structuredClone(solverTemplate);
invalidTemplate.nodes[0].roadBundleAssignments[0].laneAssignments.push({ fromLaneId: "missing", toLaneId: "e3" });
assert.equal(M.analyzeFlowMatching(invalidTemplate).conflictCount, 1, "invalid lane references must be reported");

const networkView = M.buildLaneNetworkView(solverTemplate, {
  lanes: [
    { id: "w1", traffic: { sourceNodeId: "west_node", targetNodeId: "junction" }, geometry: { renderPath: [{ x: 0, y: 10 }, { x: 10, y: 10 }] } },
    { id: "e4", traffic: { sourceNodeId: "junction", targetNodeId: "east_node" }, geometry: { renderPath: [{ x: 10, y: 10 }, { x: 20, y: 10 }] } },
  ],
}, new Set());
assert.equal(networkView.connections.length >= 1, true);
assert.deepEqual(networkView.lanes[0].effectiveTraffic, { sourceNodeId: "west_node", targetNodeId: "junction" });

const physical = M.compilePhysicalLaneNetwork({ nodes: [{ nodeId: "junction", classification: "simple_continuation", arms: [], roadBundleAssignments: [] }, { nodeId: "west_node", classification: "terminal", arms: [] }] }, {
  nodes: [{ id: "west_node", position: { x: 0, y: 0 } }, { id: "junction", position: { x: 100, y: 0 } }],
  lanes: [{ id: "parallel", roadBundleId: "road", traffic: { sourceNodeId: "west_node", targetNodeId: "junction" }, geometry: { width: 28, renderPath: [{ x: 0, y: 12 }, { x: 100, y: 12 }] }, markings: {} }],
}, new Set());
assert.equal(physical.ports.find((port) => port.nodeId === "junction").point.y, 12, "cutback must preserve a lane's lateral offset instead of converging on the node center");
assert.equal(physical.summary.logicalConnectionCount, 0);

console.log("flow matcher model tests passed");
