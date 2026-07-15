export function toggleLaneMatch(assignment, fromLaneId, toLaneId) {
  if (!assignment.incomingLaneIds.includes(fromLaneId)) {
    throw new Error(`Unknown incoming lane: ${fromLaneId}`);
  }
  if (!assignment.outgoingLaneIds.includes(toLaneId)) {
    throw new Error(`Unknown outgoing lane: ${toLaneId}`);
  }
  assignment.laneAssignments ??= [];
  const index = assignment.laneAssignments.findIndex(
    (item) => item.fromLaneId === fromLaneId && item.toLaneId === toLaneId,
  );
  if (index >= 0) {
    assignment.laneAssignments.splice(index, 1);
    return false;
  }
  assignment.laneAssignments.push({ fromLaneId, toLaneId });
  assignment.laneAssignments.sort((a, b) =>
    `${a.fromLaneId}:${a.toLaneId}`.localeCompare(`${b.fromLaneId}:${b.toLaneId}`, undefined, { numeric: true }),
  );
  return true;
}

export function assignmentKey(nodeId, assignmentId) {
  return `${nodeId}::${assignmentId}`;
}

export function suggestOrderedMatches(assignment) {
  const incoming = assignment.incomingLaneIds ?? [];
  const outgoing = assignment.outgoingLaneIds ?? [];
  if (!incoming.length || !outgoing.length) return [];
  if (incoming.length >= outgoing.length) {
    return incoming.map((fromLaneId, index) => ({
      fromLaneId,
      toLaneId: outgoing[Math.round(index * (outgoing.length - 1) / Math.max(incoming.length - 1, 1))],
    }));
  }
  return outgoing.map((toLaneId, index) => ({
    fromLaneId: incoming[Math.round(index * (incoming.length - 1) / Math.max(outgoing.length - 1, 1))],
    toLaneId,
  }));
}

function lanePort(angleDegrees, index, count) {
  const angle = angleDegrees * Math.PI / 180;
  const offset = (index - (count - 1) / 2) * 0.18;
  return { x: Math.cos(angle) - Math.sin(angle) * offset, y: Math.sin(angle) + Math.cos(angle) * offset };
}

function suggestionCost(matches, fromIds, toIds, fromAngle, toAngle) {
  return matches.reduce((sum, match) => {
    const a = lanePort(fromAngle, fromIds.indexOf(match.fromLaneId), fromIds.length);
    const b = lanePort(toAngle, toIds.indexOf(match.toLaneId), toIds.length);
    return sum + (a.x - b.x) ** 2 + (a.y - b.y) ** 2;
  }, 0);
}

function segmentsCross(a, b, c, d) {
  const side = (p, q, r) => (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x);
  return side(a, b, c) * side(a, b, d) < -1e-7 && side(c, d, a) * side(c, d, b) < -1e-7;
}

export function suggestSpatialMatches(node, assignment) {
  const fromArm = node.arms.find((arm) => arm.roadBundleId === assignment.fromRoadBundleId);
  const toArm = node.arms.find((arm) => arm.roadBundleId === assignment.toRoadBundleId);
  if (!fromArm || !toArm) return suggestOrderedMatches(assignment);
  const direct = suggestOrderedMatches(assignment);
  const reversedAssignment = { ...assignment, outgoingLaneIds: [...assignment.outgoingLaneIds].reverse() };
  const reversed = suggestOrderedMatches(reversedAssignment);
  return suggestionCost(direct, assignment.incomingLaneIds, assignment.outgoingLaneIds, fromArm.angleDegrees, toArm.angleDegrees)
    <= suggestionCost(reversed, assignment.incomingLaneIds, assignment.outgoingLaneIds, fromArm.angleDegrees, toArm.angleDegrees) ? direct : reversed;
}

function normalizedTurnDegrees(fromAngle, toAngle) {
  let value = toAngle - (fromAngle + 180);
  while (value > 180) value -= 360;
  while (value <= -180) value += 360;
  return Math.abs(value);
}

function assignmentBetween(node, fromRoadBundleId, toRoadBundleId) {
  return (node.roadBundleAssignments ?? []).find(
    (item) => item.fromRoadBundleId === fromRoadBundleId && item.toRoadBundleId === toRoadBundleId,
  );
}

function fillAssignment(node, assignment) {
  if (!assignment || assignment.laneAssignments?.length) return 0;
  assignment.laneAssignments = suggestSpatialMatches(node, assignment);
  return assignment.laneAssignments.length;
}

function fillAccessAssignment(node, assignment) {
  if (!assignment || assignment.laneAssignments?.length) return 0;
  const fromArm = node.arms.find((arm) => arm.roadBundleId === assignment.fromRoadBundleId);
  const toArm = node.arms.find((arm) => arm.roadBundleId === assignment.toRoadBundleId);
  let best = null;
  for (const fromLaneId of assignment.incomingLaneIds ?? []) for (const toLaneId of assignment.outgoingLaneIds ?? []) {
    const match = { fromLaneId, toLaneId };
    const cost = suggestionCost([match], assignment.incomingLaneIds, assignment.outgoingLaneIds, fromArm.angleDegrees, toArm.angleDegrees);
    if (!best || cost < best.cost) best = { match, cost };
  }
  if (!best) return 0;
  assignment.laneAssignments = [best.match];
  return 1;
}

export function applyDeterministicMatches(template) {
  const changedNodeIds = [];
  let autoAddedMatchCount = 0;
  for (const node of template.nodes ?? []) {
    if (node.assignmentPolicy !== "manual_road_bundle_mapping") continue;
    const before = autoAddedMatchCount;
    if (node.arms.length === 2) {
      for (const assignment of node.roadBundleAssignments ?? []) autoAddedMatchCount += fillAssignment(node, assignment);
    } else {
      const trunks = node.arms.filter((arm) => node.trunkRoadBundleIds?.includes(arm.roadBundleId));
      const accessArms = node.arms.filter((arm) => !node.trunkRoadBundleIds?.includes(arm.roadBundleId) && arm.laneIds.length <= 2);
      if (trunks.length === 2 && accessArms.length === 1 && trunks.every((arm) => arm.laneIds.length >= 4)) {
        autoAddedMatchCount += fillAssignment(node, assignmentBetween(node, trunks[0].roadBundleId, trunks[1].roadBundleId));
        autoAddedMatchCount += fillAssignment(node, assignmentBetween(node, trunks[1].roadBundleId, trunks[0].roadBundleId));
        const access = accessArms[0];
        const intoAccess = trunks
          .filter((arm) => arm.incomingLaneIds.length && access.outgoingLaneIds.length)
          .sort((a, b) => normalizedTurnDegrees(a.angleDegrees, access.angleDegrees) - normalizedTurnDegrees(b.angleDegrees, access.angleDegrees))[0];
        const outOfAccess = trunks
          .filter((arm) => access.incomingLaneIds.length && arm.outgoingLaneIds.length)
          .sort((a, b) => normalizedTurnDegrees(access.angleDegrees, a.angleDegrees) - normalizedTurnDegrees(access.angleDegrees, b.angleDegrees))[0];
        autoAddedMatchCount += fillAccessAssignment(node, assignmentBetween(node, intoAccess?.roadBundleId, access.roadBundleId));
        autoAddedMatchCount += fillAccessAssignment(node, assignmentBetween(node, access.roadBundleId, outOfAccess?.roadBundleId));
      }
    }
    if (autoAddedMatchCount > before) changedNodeIds.push(node.nodeId);
  }
  return { autoAddedMatchCount, changedNodeIds };
}

export function analyzeFlowMatching(template) {
  const nodes = [];
  let conflictCount = 0;
  let uncoveredLanePortCount = 0;
  for (const node of template.nodes ?? []) {
    if (node.assignmentPolicy !== "manual_road_bundle_mapping") continue;
    const incoming = new Set(node.arms?.flatMap((arm) => arm.incomingLaneIds ?? []) ?? []);
    const outgoing = new Set(node.arms?.flatMap((arm) => arm.outgoingLaneIds ?? []) ?? []);
    const coveredIncoming = new Set();
    const coveredOutgoing = new Set();
    const conflicts = [];
    const pairs = new Set();
    const trunkSegments = [];
    for (const assignment of node.roadBundleAssignments ?? []) {
      const validIncoming = new Set(assignment.incomingLaneIds ?? []);
      const validOutgoing = new Set(assignment.outgoingLaneIds ?? []);
      for (const match of assignment.laneAssignments ?? []) {
        const key = `${match.fromLaneId}->${match.toLaneId}`;
        if (!validIncoming.has(match.fromLaneId) || !validOutgoing.has(match.toLaneId)) conflicts.push(`无效匹配 ${key}`);
        else { coveredIncoming.add(match.fromLaneId); coveredOutgoing.add(match.toLaneId); }
        if (pairs.has(key)) conflicts.push(`重复匹配 ${key}`);
        pairs.add(key);
        if (assignment.relation === "trunk_continuation") {
          const fromArm = node.arms.find((arm) => arm.roadBundleId === assignment.fromRoadBundleId);
          const toArm = node.arms.find((arm) => arm.roadBundleId === assignment.toRoadBundleId);
          trunkSegments.push({ assignmentId: assignment.id, a: lanePort(fromArm.angleDegrees, assignment.incomingLaneIds.indexOf(match.fromLaneId), assignment.incomingLaneIds.length), b: lanePort(toArm.angleDegrees, assignment.outgoingLaneIds.indexOf(match.toLaneId), assignment.outgoingLaneIds.length) });
        }
      }
      const actual = assignment.laneAssignments ?? [];
      if (actual.length > 1 && new Set(actual.map((item) => item.fromLaneId)).size === actual.length && new Set(actual.map((item) => item.toLaneId)).size === actual.length) {
        const expected = suggestSpatialMatches(node, assignment);
        const expectedPairs = new Set(expected.map((item) => `${item.fromLaneId}->${item.toLaneId}`));
        if (actual.some((item) => !expectedPairs.has(`${item.fromLaneId}->${item.toLaneId}`))) conflicts.push(`车道顺序交叉 ${assignment.id}`);
      }
    }
    if (trunkSegments.some((first, index) => trunkSegments.slice(index + 1).some((second) => first.assignmentId !== second.assignmentId && segmentsCross(first.a, first.b, second.a, second.b)))) {
      conflicts.push("主路对向车道发生几何交叉，请检查车道方向");
    }
    const uncoveredIncomingLaneIds = [...incoming].filter((id) => !coveredIncoming.has(id));
    const uncoveredOutgoingLaneIds = [...outgoing].filter((id) => !coveredOutgoing.has(id));
    const emptyCandidateCount = (node.roadBundleAssignments ?? []).filter((item) => !item.laneAssignments?.length).length;
    const freedomCount = uncoveredIncomingLaneIds.length + uncoveredOutgoingLaneIds.length;
    conflictCount += conflicts.length;
    uncoveredLanePortCount += freedomCount;
    nodes.push({ nodeId: node.nodeId, conflictCount: conflicts.length, conflicts, uncoveredIncomingLaneIds, uncoveredOutgoingLaneIds, uncoveredLanePortCount: freedomCount, freedomCount, emptyCandidateCount, complete: conflicts.length === 0 && freedomCount === 0 });
  }
  return { conflictCount, uncoveredLanePortCount, completeNodeCount: nodes.filter((node) => node.complete).length, nodeCount: nodes.length, nodes };
}

export function buildLaneNetworkView(template, road, reversedLaneIds = new Set()) {
  const laneById = new Map((road.lanes ?? []).map((lane) => [lane.id, lane]));
  const lanes = (road.lanes ?? []).map((lane) => ({
    id: lane.id,
    roadBundleId: lane.roadBundleId,
    renderPath: lane.geometry.renderPath.map((point) => ({ ...point })),
    effectiveTraffic: reversedLaneIds.has(lane.id)
      ? { sourceNodeId: lane.traffic.targetNodeId, targetNodeId: lane.traffic.sourceNodeId }
      : { sourceNodeId: lane.traffic.sourceNodeId, targetNodeId: lane.traffic.targetNodeId },
    reversed: reversedLaneIds.has(lane.id),
  }));
  const connections = [];
  for (const node of template.nodes ?? []) {
    for (const assignment of node.roadBundleAssignments ?? []) {
      for (const match of assignment.laneAssignments ?? []) {
        if (!laneById.has(match.fromLaneId) || !laneById.has(match.toLaneId)) continue;
        connections.push({ nodeId: node.nodeId, fromLaneId: match.fromLaneId, toLaneId: match.toLaneId });
      }
    }
  }
  return { lanes, connections };
}

function pointDistance(a, b) { return Math.hypot(a.x - b.x, a.y - b.y); }
function pointUnit(a, b) { const size = pointDistance(a, b) || 1; return { x: (b.x - a.x) / size, y: (b.y - a.y) / size }; }
function cubicPoints(a, c1, c2, b, count = 20) {
  return Array.from({ length: count + 1 }, (_, index) => { const t = index / count; return { x: (1-t)**3*a.x + 3*(1-t)**2*t*c1.x + 3*(1-t)*t*t*c2.x + t**3*b.x, y: (1-t)**3*a.y + 3*(1-t)**2*t*c1.y + 3*(1-t)*t*t*c2.y + t**3*b.y }; });
}

export function compilePhysicalLaneNetwork(template, road, reversedLaneIds = new Set()) {
  const nodes = new Map(road.nodes.map((node) => [node.id, node]));
  const templateNodes = new Map(template.nodes.map((node) => [node.nodeId, node]));
  const ports = new Map();
  const lanes = road.lanes.map((lane) => {
    const reversed = reversedLaneIds.has(lane.id);
    const sourceNodeId = reversed ? lane.traffic.targetNodeId : lane.traffic.sourceNodeId;
    const targetNodeId = reversed ? lane.traffic.sourceNodeId : lane.traffic.targetNodeId;
    const source = nodes.get(sourceNodeId).position;
    let path = lane.geometry.renderPath.map((point) => ({ ...point }));
    if (pointDistance(path.at(-1), source) < pointDistance(path[0], source)) path.reverse();
    const pathSpan = pointDistance(path[0], path.at(-1));
    const sourceCutback = Math.min(templateNodes.get(sourceNodeId)?.classification === "chaotic_intersection" ? 38 : 24, pathSpan * .35);
    const targetCutback = Math.min(templateNodes.get(targetNodeId)?.classification === "chaotic_intersection" ? 38 : 24, pathSpan * .35);
    const sourceTravel = pointUnit(path[0], path[1]);
    const targetTravel = pointUnit(path.at(-2), path.at(-1));
    path[0] = { x: path[0].x + sourceTravel.x * sourceCutback, y: path[0].y + sourceTravel.y * sourceCutback };
    path[path.length - 1] = { x: path.at(-1).x - targetTravel.x * targetCutback, y: path.at(-1).y - targetTravel.y * targetCutback };
    ports.set(`${sourceNodeId}:${lane.id}`, { nodeId: sourceNodeId, laneId: lane.id, point: path[0], travel: sourceTravel, incoming: false, width: lane.geometry.width, roadBundleId: lane.roadBundleId });
    ports.set(`${targetNodeId}:${lane.id}`, { nodeId: targetNodeId, laneId: lane.id, point: path.at(-1), travel: targetTravel, incoming: true, width: lane.geometry.width, roadBundleId: lane.roadBundleId });
    return { id: lane.id, roadBundleId: lane.roadBundleId, renderPath: path, effectiveTraffic: { sourceNodeId, targetNodeId }, width: lane.geometry.width, markings: lane.markings, reversed };
  });
  const connections = [];
  for (const node of template.nodes) for (const assignment of node.roadBundleAssignments ?? []) for (const match of assignment.laneAssignments ?? []) {
    const source = ports.get(`${node.nodeId}:${match.fromLaneId}`), target = ports.get(`${node.nodeId}:${match.toLaneId}`);
    if (!source?.incoming || !target || target.incoming) continue;
    const span = pointDistance(source.point, target.point);
    const handle = Math.min(42, Math.max(12, span * .42));
    connections.push({ nodeId: node.nodeId, fromLaneId: match.fromLaneId, toLaneId: match.toLaneId, relation: assignment.relation, priority: assignment.relation === "trunk_continuation" ? 0 : 1, path: cubicPoints(source.point, { x: source.point.x + source.travel.x * handle, y: source.point.y + source.travel.y * handle }, { x: target.point.x - target.travel.x * handle, y: target.point.y - target.travel.y * handle }, target.point) });
  }
  const junctions = template.nodes.filter((node) => node.arms.length >= 2).map((node) => {
    const approaches = node.arms.map((arm) => ({ roadBundleId: arm.roadBundleId, angleDegrees: arm.angleDegrees, laneCount: arm.laneIds.length, width: Math.max(28, arm.laneIds.length * 14) }));
    const chaotic = node.classification === "chaotic_intersection";
    return { nodeId: node.nodeId, center: { ...node.position }, chaotic, radius: Math.max(chaotic ? 39 : 25, ...approaches.map((arm) => arm.width / 2 + 8)), approaches };
  });
  for (const junction of junctions) {
    const selected = [];
    const candidates = connections.filter((item) => item.nodeId === junction.nodeId).sort((a, b) => a.priority - b.priority || a.fromLaneId.localeCompare(b.fromLaneId, undefined, { numeric: true }));
    for (const candidate of candidates) {
      const a = candidate.path[0], b = candidate.path.at(-1);
      candidate.rendered = !junction.chaotic && !selected.some((item) => segmentsCross(a, b, item.path[0], item.path.at(-1)));
      if (candidate.rendered) selected.push(candidate);
    }
  }
  return { lanes, connections, junctions, ports: [...ports.values()], summary: { logicalConnectionCount: connections.length, renderedConnectionCount: connections.filter((item) => item.rendered).length, absorbedConnectionCount: connections.filter((item) => !item.rendered).length } };
}

function suggestedMode(incomingCount, outgoingCount) {
  if (incomingCount > outgoingCount) return "merge";
  if (incomingCount < outgoingCount) return "split";
  return "continue";
}

export function rebuildDirections(template, road, reversedLaneIds = new Set()) {
  const lanes = new Map(road.lanes.map((lane) => [lane.id, lane]));
  for (const node of template.nodes) {
    for (const arm of node.arms ?? []) {
      arm.incomingLaneIds = arm.laneIds.filter((laneId) => {
        const lane = lanes.get(laneId);
        if (!lane) return false;
        return reversedLaneIds.has(laneId) ? lane.traffic.sourceNodeId === node.nodeId : lane.traffic.targetNodeId === node.nodeId;
      });
      arm.outgoingLaneIds = arm.laneIds.filter((laneId) => {
        const lane = lanes.get(laneId);
        if (!lane) return false;
        return reversedLaneIds.has(laneId) ? lane.traffic.targetNodeId === node.nodeId : lane.traffic.sourceNodeId === node.nodeId;
      });
    }
    if (node.assignmentPolicy !== "manual_road_bundle_mapping") continue;
    const existing = new Map((node.roadBundleAssignments ?? []).map((assignment) => [assignment.id, assignment]));
    const rebuilt = [];
    for (const source of node.arms) {
      for (const target of node.arms) {
        if (source === target || !source.incomingLaneIds.length || !target.outgoingLaneIds.length) continue;
        const id = `${source.roadBundleId}->${target.roadBundleId}`;
        const previous = existing.get(id);
        const validIncoming = new Set(source.incomingLaneIds);
        const validOutgoing = new Set(target.outgoingLaneIds);
        rebuilt.push({
          id,
          status: "needs_review",
          relation: node.trunkRoadBundleIds?.includes(source.roadBundleId) && node.trunkRoadBundleIds?.includes(target.roadBundleId) ? "trunk_continuation" : "branch_merge_or_split",
          fromRoadBundleId: source.roadBundleId,
          toRoadBundleId: target.roadBundleId,
          incomingLaneIds: [...source.incomingLaneIds],
          outgoingLaneIds: [...target.outgoingLaneIds],
          suggestedMode: suggestedMode(source.incomingLaneIds.length, target.outgoingLaneIds.length),
          laneAssignments: (previous?.laneAssignments ?? []).filter((item) => validIncoming.has(item.fromLaneId) && validOutgoing.has(item.toLaneId)),
        });
      }
    }
    node.roadBundleAssignments = rebuilt;
  }
  return template;
}

export function buildConfirmedExport(template, road = null, reversedLaneIds = new Set()) {
  return {
    schema: "road_logic_modeler.confirmed-node-flow.v1",
    sourceSchema: template.schema,
    laneDirectionOverrides: road ? [...reversedLaneIds].sort().map((laneId) => {
      const lane = road.lanes.find((item) => item.id === laneId);
      return { laneId, originalSourceNodeId: lane.traffic.sourceNodeId, originalTargetNodeId: lane.traffic.targetNodeId, sourceNodeId: lane.traffic.targetNodeId, targetNodeId: lane.traffic.sourceNodeId };
    }) : [],
    nodes: template.nodes
      .map((node) => ({
        nodeId: node.nodeId,
        classification: node.classification,
        roadBundleAssignments: (node.roadBundleAssignments ?? [])
          .filter((assignment) => assignment.laneAssignments?.length)
          .map((assignment) => ({
            id: assignment.id,
            fromRoadBundleId: assignment.fromRoadBundleId,
            toRoadBundleId: assignment.toRoadBundleId,
            mode: assignment.suggestedMode,
            status: "confirmed",
            laneAssignments: assignment.laneAssignments.map((item) => ({ ...item })),
          })),
      }))
      .filter((node) => node.roadBundleAssignments.length),
  };
}
