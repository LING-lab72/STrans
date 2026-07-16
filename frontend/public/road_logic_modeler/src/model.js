(function () {
  "use strict";

  const G = window.RoadLogicModeler.geometry;

  const NODE_TYPES = [
    ["junction", "路口"],
    ["boundary", "边界"],
    ["building_anchor", "建筑物端点"],
    ["lane_point", "道路内节点"]
  ];

  const INTERPOLATIONS = [
    ["line", "直线"],
    ["quadratic", "二次曲线"],
    ["cubic", "三次样条"]
  ];

  const DIRECTIONS = [
    ["1-2", "1 → 2"],
    ["2-1", "2 → 1"]
  ];

  const ARROWS = [
    ["none", "无"],
    ["forward", "向前"],
    ["backward", "向后"],
    ["forward_left", "前左"],
    ["forward_right", "前右"],
    ["left", "向左"],
    ["right", "向右"]
  ];

  const LINE_STYLES = [
    ["solid", "实线"],
    ["dashed", "虚线"],
    ["none", "无"]
  ];

  const CAMERA_PRESETS = [
    ["live1", "桥面"], ["live2", "停车场出口"], ["live3", "行人检测"],
    ["live4", "消防车识别"], ["live5", "桥出口"], ["live6", "桥入口"],
    ["live7", "道路2"], ["live8", "隧道（事故识别）"], ["live9", "隧道（车辆数量）"],
    ["live10", "道路3"], ["live11", "停车场入口"], ["live12", "道路1"]
  ].map(([id, place]) => ({ id, place, url: `rtsp://10.126.59.120:8554/live/${id}` }));

  function createModel() {
    return normalize({
      schema: "road_logic_modeler.v1",
      name: "road_logic_model",
      world: { width: 1200, height: 760, unit: "cm", gridSize: 20 },
      nodes: [],
      lanes: [],
      laneEndpointGroups: [],
      buildings: [],
      cameraCalibrations: [],
      cameras: []
    });
  }

  function normalize(input) {
    const model = input && typeof input === "object" ? input : {};
    model.schema = "road_logic_modeler.v1";
    model.name = model.name || "road_logic_model";
    model.world = model.world || {};
    model.world.width = number(model.world.width, 1200);
    model.world.height = number(model.world.height, 760);
    model.world.unit = model.world.unit || "cm";
    model.world.gridSize = Math.max(5, number(model.world.gridSize, 20));
    model.nodes = Array.isArray(model.nodes) ? model.nodes : [];
    model.lanes = Array.isArray(model.lanes) ? model.lanes : [];
    model.laneEndpointGroups = Array.isArray(model.laneEndpointGroups) ? model.laneEndpointGroups : [];
    model.buildings = Array.isArray(model.buildings) ? model.buildings : [];
    model.cameraCalibrations = Array.isArray(model.cameraCalibrations) ? model.cameraCalibrations : [];
    model.cameras = Array.isArray(model.cameras) ? model.cameras : [];

    model.nodes.forEach((node, i) => {
      node.id = node.id || nextId("node", model.nodes, i + 1);
      node.name = node.name || `端点 ${i + 1}`;
      node.type = node.type || "junction";
      node.x = number(node.x, 0);
      node.y = number(node.y, 0);
      node.z = number(node.z, 0);
      node.buildingId = node.buildingId || "";
      node.groupId = node.groupId || "";
    });

    model.lanes.forEach((lane, i) => {
      lane.id = lane.id || nextId("lane", model.lanes, i + 1);
      lane.name = lane.name || `车道 ${i + 1}`;
      lane.endpoint1 = lane.endpoint1 || lane.from || "";
      lane.endpoint2 = lane.endpoint2 || lane.to || "";
      delete lane.from;
      delete lane.to;
      lane.height = lane.height === "" || lane.height === null || lane.height === undefined ? null : number(lane.height, 0);
      lane.width = Math.max(4, number(lane.width, 28));
      lane.interpolation = lane.interpolation || "line";
      lane.controlPoints = Array.isArray(lane.controlPoints) ? lane.controlPoints : [];
      lane.direction = lane.direction || "1-2";
      lane.endpoint1Arrow = lane.endpoint1Arrow || lane.arrowFrom || "none";
      lane.endpoint2Arrow = lane.endpoint2Arrow || lane.arrowTo || "forward";
      lane.leftLineStyle = lane.leftLineStyle || "solid";
      lane.rightLineStyle = lane.rightLineStyle || "solid";
      lane.renderOrder = number(lane.renderOrder, 0);
      delete lane.arrowFrom;
      delete lane.arrowTo;
    });

    model.laneEndpointGroups.forEach((group, i) => {
      group.id = group.id || nextId("group", model.laneEndpointGroups, i + 1);
      group.name = group.name || `车道端点组 ${i + 1}`;
      group.nodeIds = Array.isArray(group.nodeIds) ? group.nodeIds : [];
      group.order = group.order || "auto";
      group.spacing = Math.max(4, number(group.spacing, 36));
      group.angle = number(group.angle, 90);
    });

    model.buildings.forEach((building, i) => {
      building.id = building.id || nextId("building", model.buildings, i + 1);
      building.name = building.name || `建筑物 ${i + 1}`;
      building.x = number(building.x, 0);
      building.y = number(building.y, 0);
      building.width = Math.max(10, number(building.width, 120));
      building.height = Math.max(10, number(building.height, 80));
      building.anchorNodeIds = Array.isArray(building.anchorNodeIds) ? building.anchorNodeIds : [];
    });

    migrateLegacyCameraCalibrations(model);
    normalizeCameraCalibrations(model);

    model.cameras.forEach((camera, i) => {
      camera.id = camera.id || nextId("cam", model.cameras, i + 1);
      camera.name = camera.name || `摄像头 ${i + 1}`;
      camera.place = camera.place || "";
      camera.x = number(camera.x, 0);
      camera.y = number(camera.y, 0);
      camera.direction = number(camera.direction, 0);
      camera.fov = number(camera.fov, 60);
      camera.range = number(camera.range, 240);
      camera.height = camera.height === null || camera.height === undefined || camera.height === "" ? 500 : Number(camera.height);
      camera.coverage = camera.coverage || {};
      camera.coverage.gridCells = Array.isArray(camera.coverage.gridCells) ? camera.coverage.gridCells : [];
      camera.rtspUrl = camera.rtspUrl || "";
      camera.streamPresetId = camera.streamPresetId || "";
      camera.calibrationId = model.cameraCalibrations.some((item) => item.id === camera.calibrationId) ? camera.calibrationId : "";
      camera.pointBindings = normalizePointBindings(camera.pointBindings, camera.coverage.gridCells);
      delete camera.image;
      delete camera.imagePoints;
      delete camera.imageLines;
    });

    syncGroupMembership(model);
    return model;
  }

  function migrateLegacyCameraCalibrations(model) {
    model.cameras.forEach((camera, index) => {
      const legacyPoints = Array.isArray(camera.imagePoints) ? camera.imagePoints : [];
      if (camera.calibrationId || (!camera.image && !legacyPoints.length)) return;
      const calibration = {
        id: nextId("calibration", model.cameraCalibrations),
        name: `${camera.name || `摄像头 ${index + 1}`} 标定`,
        image: camera.image || null,
        points: legacyPoints.map((point) => ({ id: point.id, name: point.name, x: point.x, y: point.y })),
        lines: Array.isArray(camera.imageLines) ? camera.imageLines : []
      };
      model.cameraCalibrations.push(calibration);
      camera.calibrationId = calibration.id;
      camera.pointBindings = legacyPoints.map((point) => bindingFromLegacyTarget(point.id, point.target)).filter(Boolean);
    });
  }

  function bindingFromLegacyTarget(imagePointId, target) {
    if (!target || !imagePointId) return null;
    if (target.type === "grid_cell" && Array.isArray(target.cell)) {
      return { imagePointId, gridCellId: gridCellId(target.cell), gridCell: target.cell.slice(0, 2) };
    }
    if (target.type === "world_point" && target.point) return { imagePointId, worldPoint: target.point };
    if (target.type === "node") return { imagePointId, nodeId: target.nodeId || "" };
    if (target.type === "lane") return { imagePointId, laneId: target.laneId || "" };
    return null;
  }

  function normalizeCameraCalibrations(model) {
    const usedCalibrationIds = new Set();
    model.cameraCalibrations.forEach((calibration, index) => {
      calibration.id = uniqueId(calibration.id, "calibration", usedCalibrationIds, index + 1);
      calibration.name = calibration.name || `画面标定 ${index + 1}`;
      calibration.image = calibration.image || null;
      if (calibration.image) {
        calibration.image.name = calibration.image.name || "";
        if (typeof calibration.image.dataUrl !== "string" || !calibration.image.dataUrl) delete calibration.image.dataUrl;
        calibration.image.width = number(calibration.image.width, 0);
        calibration.image.height = number(calibration.image.height, 0);
        calibration.image.capturedAt = calibration.image.capturedAt || "";
      }
      const usedPointIds = new Set();
      calibration.points = Array.isArray(calibration.points) ? calibration.points : [];
      calibration.points.forEach((point, pointIndex) => {
        point.id = uniqueId(point.id, "imgpt", usedPointIds, pointIndex + 1);
        point.name = point.name || `画面点 ${pointIndex + 1}`;
        point.x = number(point.x, 0);
        point.y = number(point.y, 0);
      });
      const pointIds = new Set(calibration.points.map((point) => point.id));
      const usedLineIds = new Set();
      calibration.lines = (Array.isArray(calibration.lines) ? calibration.lines : [])
        .filter((line) => pointIds.has(line.fromPointId) && pointIds.has(line.toPointId) && line.fromPointId !== line.toPointId)
        .map((line, lineIndex) => ({ id: uniqueId(line.id, "imgline", usedLineIds, lineIndex + 1), fromPointId: line.fromPointId, toPointId: line.toPointId }));
    });
  }

  function uniqueId(candidate, prefix, used, start) {
    let id = candidate || `${prefix}_${start}`;
    let suffix = start;
    while (used.has(id)) id = `${prefix}_${++suffix}`;
    used.add(id);
    return id;
  }

  function gridCellId(cell) {
    return `grid_${number(cell?.[0], 0)}_${number(cell?.[1], 0)}`;
  }

  function normalizePointBindings(bindings, coverageCells) {
    const byPoint = new Map();
    (Array.isArray(bindings) ? bindings : []).forEach((binding) => {
      if (!binding?.imagePointId) return;
      const clean = { imagePointId: binding.imagePointId };
      if (binding.worldPoint) clean.worldPoint = { x: number(binding.worldPoint.x, 0), y: number(binding.worldPoint.y, 0), height: binding.worldPoint.height === null || binding.worldPoint.height === undefined || binding.worldPoint.height === "" ? 500 : Number(binding.worldPoint.height) };
      if (Array.isArray(binding.gridCell)) {
        clean.gridCell = [number(binding.gridCell[0], 0), number(binding.gridCell[1], 0)];
        clean.gridCellId = gridCellId(clean.gridCell);
        if (!coverageCells.some((cell) => gridCellId(cell) === clean.gridCellId)) coverageCells.push(clean.gridCell.slice());
      } else if (binding.nodeId) clean.nodeId = binding.nodeId;
      else if (binding.laneId) clean.laneId = binding.laneId;
      else if (binding.buildingId) clean.buildingId = binding.buildingId;
      if (!byPoint.has(clean.imagePointId)) byPoint.set(clean.imagePointId, clean);
    });
    return [...byPoint.values()];
  }

  function toggleCalibrationLine(calibration, fromPointId, toPointId) {
    if (!calibration || !fromPointId || !toPointId || fromPointId === toPointId) return null;
    const pointIds = new Set((calibration.points || []).map((point) => point.id));
    if (!pointIds.has(fromPointId) || !pointIds.has(toPointId)) return null;
    calibration.lines = Array.isArray(calibration.lines) ? calibration.lines : [];
    const index = calibration.lines.findIndex((line) =>
      (line.fromPointId === fromPointId && line.toPointId === toPointId) ||
      (line.fromPointId === toPointId && line.toPointId === fromPointId)
    );
    if (index >= 0) {
      calibration.lines.splice(index, 1);
      return false;
    }
    calibration.lines.push({ id: nextId("imgline", calibration.lines), fromPointId, toPointId });
    return true;
  }

  function number(value, fallback) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function nextId(prefix, items, start) {
    const used = new Set(items.map((item) => item.id));
    let i = start || items.length + 1;
    while (used.has(`${prefix}_${i}`)) i += 1;
    return `${prefix}_${i}`;
  }

  function nodeById(model, id) {
    return model.nodes.find((node) => node.id === id);
  }

  function laneById(model, id) {
    return model.lanes.find((lane) => lane.id === id);
  }

  function buildingById(model, id) {
    return model.buildings.find((building) => building.id === id);
  }

  function cameraById(model, id) {
    return model.cameras.find((camera) => camera.id === id);
  }

  function connectedLanes(model, nodeId) {
    return model.lanes.filter((lane) => lane.endpoint1 === nodeId || lane.endpoint2 === nodeId);
  }

  function createNodeGroup(model, center, options = {}) {
    const count = Math.max(1, Math.round(number(options.count, 2)));
    const spacing = Math.max(4, number(options.spacing, 36));
    const angle = number(options.angle, 90);
    const radians = angle * Math.PI / 180;
    const group = {
      id: nextId("group", model.laneEndpointGroups),
      name: `道路节点组 ${model.laneEndpointGroups.length + 1}`,
      nodeIds: [], order: "manual", spacing, angle
    };
    for (let index = 0; index < count; index += 1) {
      const offset = (index - (count - 1) / 2) * spacing;
      const node = {
        id: nextId("node", model.nodes), name: `${group.name} · ${index + 1}`, type: "lane_point",
        x: number(center.x, 0) + Math.cos(radians) * offset,
        y: number(center.y, 0) + Math.sin(radians) * offset,
        z: 0, buildingId: "", groupId: group.id
      };
      model.nodes.push(node);
      group.nodeIds.push(node.id);
    }
    model.laneEndpointGroups.push(group);
    return group;
  }

  function groupCenter(model, group) {
    const nodes = group.nodeIds.map((id) => nodeById(model, id)).filter(Boolean);
    if (!nodes.length) return null;
    return nodes.reduce((center, node) => ({ x: center.x + node.x / nodes.length, y: center.y + node.y / nodes.length }), { x: 0, y: 0 });
  }

  function moveNodeGroup(model, groupId, center) {
    const group = model.laneEndpointGroups.find((item) => item.id === groupId);
    const current = group && groupCenter(model, group);
    if (!group || !current) return false;
    const dx = number(center.x, current.x) - current.x;
    const dy = number(center.y, current.y) - current.y;
    group.nodeIds.forEach((id) => {
      const node = nodeById(model, id);
      if (node) { node.x += dx; node.y += dy; }
    });
    return true;
  }

  function connectNodeGroups(model, fromGroupId, toGroupId) {
    const from = model.laneEndpointGroups.find((group) => group.id === fromGroupId);
    const to = model.laneEndpointGroups.find((group) => group.id === toGroupId);
    if (!from || !to || from.id === to.id) return [];
    const count = Math.min(from.nodeIds.length, to.nodeIds.length);
    const created = [];
    for (let index = 0; index < count; index += 1) {
      const endpoint1 = from.nodeIds[index];
      const endpoint2 = to.nodeIds[index];
      if (!nodeById(model, endpoint1) || !nodeById(model, endpoint2)) continue;
      const lane = {
        id: nextId("lane", model.lanes), name: `车道 ${model.lanes.length + 1}`,
        endpoint1, endpoint2, height: null, width: 28, interpolation: "line", controlPoints: [],
        direction: "1-2", endpoint1Arrow: "none", endpoint2Arrow: "forward",
        leftLineStyle: "solid", rightLineStyle: "solid", renderOrder: 0
      };
      model.lanes.push(lane);
      created.push(lane);
    }
    return created;
  }

  function deleteNodeGroup(model, groupId) {
    const index = model.laneEndpointGroups.findIndex((group) => group.id === groupId);
    if (index < 0) return false;
    const nodeIds = new Set(model.laneEndpointGroups[index].nodeIds);
    model.laneEndpointGroups.splice(index, 1);
    model.nodes = model.nodes.filter((node) => !nodeIds.has(node.id));
    model.lanes = model.lanes.filter((lane) => !nodeIds.has(lane.endpoint1) && !nodeIds.has(lane.endpoint2));
    return true;
  }

  function convertNodeToGroup(model, nodeId) {
    const source = nodeById(model, nodeId);
    const lanes = connectedLanes(model, nodeId).slice().sort((a, b) => a.renderOrder - b.renderOrder || a.id.localeCompare(b.id));
    if (!source || !lanes.length) return null;
    let dx = 0, dy = 0;
    lanes.forEach((lane) => {
      const other = nodeById(model, lane.endpoint1 === nodeId ? lane.endpoint2 : lane.endpoint1);
      if (!other) return;
      const length = Math.hypot(other.x - source.x, other.y - source.y) || 1;
      dx += (other.x - source.x) / length;
      dy += (other.y - source.y) / length;
    });
    if (dx < 0 || (Math.abs(dx) < 1e-9 && dy < 0)) { dx = -dx; dy = -dy; }
    const directionLength = Math.hypot(dx, dy) || 1;
    const normal = { x: -dy / directionLength, y: dx / directionLength };
    const spacing = Math.max(...lanes.map((lane) => lane.width || 28));
    const group = {
      id: nextId("group", model.laneEndpointGroups), name: `${source.name || source.id} 道路截面`,
      nodeIds: [], order: "manual", spacing, angle: Math.atan2(normal.y, normal.x) * 180 / Math.PI
    };
    lanes.forEach((lane, index) => {
      const offset = (index - (lanes.length - 1) / 2) * spacing;
      const node = {
        id: nextId("node", model.nodes), name: `${group.name} · ${index + 1}`, type: "lane_point",
        x: source.x + normal.x * offset, y: source.y + normal.y * offset,
        z: source.z || 0, buildingId: "", groupId: group.id
      };
      model.nodes.push(node);
      group.nodeIds.push(node.id);
      if (lane.endpoint1 === nodeId) lane.endpoint1 = node.id;
      if (lane.endpoint2 === nodeId) lane.endpoint2 = node.id;
    });
    model.nodes = model.nodes.filter((node) => node.id !== nodeId);
    model.laneEndpointGroups.forEach((item) => { item.nodeIds = item.nodeIds.filter((id) => id !== nodeId); });
    model.laneEndpointGroups.push(group);
    return group;
  }

  function laneKey(lane) {
    return [lane.endpoint1, lane.endpoint2].sort().join("::");
  }

  function lanePortKey(model, nodeId) {
    const node = nodeById(model, nodeId);
    return node?.groupId ? `group:${node.groupId}` : `node:${nodeId}`;
  }

  function laneBundleKey(model, lane) {
    return [lanePortKey(model, lane.endpoint1), lanePortKey(model, lane.endpoint2)].sort().join("::");
  }

  function lanePath(model, lane) {
    const a = nodeById(model, lane.endpoint1);
    const b = nodeById(model, lane.endpoint2);
    if (!a || !b) return [];
    return [
      { x: a.x, y: a.y },
      ...(lane.controlPoints || []).map((p) => ({ x: Number(p[0]), y: Number(p[1]) })),
      { x: b.x, y: b.y }
    ];
  }

  function pointBindingCandidates(model, point) {
    const candidates = [];
    model.nodes.forEach((node) => {
      if (G.distance(point, node) <= 10) candidates.push({ type: "node", id: node.id, label: `节点 ${node.name || node.id}` });
    });
    model.lanes.forEach((lane) => {
      if (G.distanceToPolyline(point, lanePath(model, lane)) <= lane.width / 2) candidates.push({ type: "lane", id: lane.id, label: `道路 ${lane.name || lane.id}` });
    });
    model.buildings.forEach((building) => {
      if (Math.abs(point.x - building.x) <= building.width / 2 && Math.abs(point.y - building.y) <= building.height / 2) candidates.push({ type: "building", id: building.id, label: `建筑物 ${building.name || building.id}` });
    });
    return candidates;
  }

  function laneSideAtNode(model, lane, nodeId) {
    const node = nodeById(model, nodeId);
    const other = nodeById(model, lane.endpoint1 === nodeId ? lane.endpoint2 : lane.endpoint1);
    if (!node || !other) return "east";
    const controls = (lane.controlPoints || []).map((p) => ({ x: Number(p[0]), y: Number(p[1]) }));
    const near = lane.endpoint1 === nodeId ? controls[0] : controls[controls.length - 1];
    return G.sideFromAngle(G.angle(node, near || other));
  }

  function junctionSides(model, nodeId) {
    const sides = { north: [], east: [], south: [], west: [] };
    connectedLanes(model, nodeId).forEach((lane) => {
      sides[laneSideAtNode(model, lane, nodeId)].push(lane.id);
    });
    return sides;
  }

  function syncGroupMembership(model) {
    const claimedNodeIds = new Set();
    model.nodes.forEach((node) => { node.groupId = ""; });
    model.laneEndpointGroups.forEach((group) => {
      group.nodeIds = group.nodeIds.filter((id) => {
        const node = nodeById(model, id);
        if (!node || claimedNodeIds.has(id)) return false;
        claimedNodeIds.add(id);
        node.groupId = group.id;
        return true;
      });
    });
  }

  function buildLogic(model) {
    syncGroupMembership(model);
    const lanes = model.lanes.map((lane) => {
      const a = nodeById(model, lane.endpoint1);
      const b = nodeById(model, lane.endpoint2);
      const height = lane.height === null ? ((a?.z || 0) + (b?.z || 0)) / 2 : lane.height;
      return {
        id: lane.id,
        name: lane.name,
        endpoints: [lane.endpoint1, lane.endpoint2],
        height,
        interpolation: lane.interpolation,
        direction: lane.direction,
        arrows: { endpoint1: lane.endpoint1Arrow, endpoint2: lane.endpoint2Arrow },
        lineStyles: { left: lane.leftLineStyle, right: lane.rightLineStyle },
        path: lanePath(model, lane)
      };
    });

    const nodes = model.nodes.map((node) => ({
      id: node.id,
      name: node.name,
      type: node.type,
      position: { x: node.x, y: node.y, z: node.z },
      buildingId: node.buildingId || null,
      groupId: node.groupId || null,
      lanes: connectedLanes(model, node.id).map((lane) => lane.id),
      sides: node.type === "junction" || node.type === "boundary" ? junctionSides(model, node.id) : undefined
    }));

    const laneGroups = model.laneEndpointGroups.map((group) => {
      const ordered = orderGroupNodes(model, group);
      return {
        id: group.id,
        name: group.name,
        nodeIds: ordered.map((node) => node.id),
        mergeLaneIds: model.lanes
          .filter((lane) => ordered.some((node) => lane.endpoint1 === node.id || lane.endpoint2 === node.id))
          .map((lane) => lane.id)
      };
    });

    const cameras = model.cameras.map((camera) => {
      const cells = camera.coverage.gridCells || [];
      return {
        id: camera.id,
        name: camera.name,
        place: camera.place,
        position: { x: camera.x, y: camera.y },
        direction: camera.direction,
        fov: camera.fov,
        range: camera.range,
        gridCells: cells,
        observedLaneIds: observedLanes(model, cells),
        streamPresetId: camera.streamPresetId || null,
        rtspUrl: camera.rtspUrl,
        calibrationId: camera.calibrationId || null,
        pointBindings: camera.pointBindings.map((binding) => ({ ...binding }))
      };
    });

    return {
      nodes,
      lanes,
      laneEndpointGroups: laneGroups,
      buildings: model.buildings.map((b) => ({
        id: b.id,
        name: b.name,
        rect: { x: b.x, y: b.y, width: b.width, height: b.height },
        anchorNodeIds: b.anchorNodeIds || []
      })),
      cameraCalibrations: model.cameraCalibrations.map((calibration) => ({
        id: calibration.id,
        name: calibration.name,
        image: calibration.image ? { name: calibration.image.name, width: calibration.image.width, height: calibration.image.height, capturedAt: calibration.image.capturedAt || null } : null,
        points: calibration.points.map((point) => ({ id: point.id, name: point.name, image: { x: point.x, y: point.y } })),
        lines: calibration.lines.map((line) => ({ ...line }))
      })),
      cameras
    };
  }

  function orderGroupNodes(model, group) {
    const nodes = group.nodeIds.map((id) => nodeById(model, id)).filter(Boolean);
    if (group.order !== "auto") return nodes;
    const center = nodes.reduce((acc, node) => ({ x: acc.x + node.x / nodes.length, y: acc.y + node.y / nodes.length }), { x: 0, y: 0 });
    return nodes.slice().sort((a, b) => G.angle(center, a) - G.angle(center, b));
  }

  function observedLanes(model, cells) {
    const grid = model.world.gridSize;
    const seen = new Set();
    cells.forEach((cell) => {
      const center = G.cellCenter(cell, grid);
      model.lanes.forEach((lane) => {
        if (G.distanceToPolyline(center, lanePath(model, lane)) <= Math.max(grid * 0.72, lane.width / 2)) seen.add(lane.id);
      });
    });
    return [...seen].sort();
  }

  function exportPayload(model) {
    const clean = normalize(lightweightClone(model));
    clean.cameras.forEach((camera) => {
      delete camera.imageTargetType;
      delete camera.pendingTargetId;
      delete camera.pendingWorldPoint;
      delete camera.pendingGridCell;
    });
    return { schema: clean.schema, name: clean.name, world: clean.world, model: clean, logic: buildLogic(clean) };
  }

  function deepClone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function lightweightClone(model) {
    return JSON.parse(JSON.stringify(model, (key, value) => key === "dataUrl" ? undefined : value));
  }

  window.RoadLogicModeler = window.RoadLogicModeler || {};
  window.RoadLogicModeler.model = {
    NODE_TYPES,
    INTERPOLATIONS,
    DIRECTIONS,
    ARROWS,
    LINE_STYLES,
    CAMERA_PRESETS,
    createModel,
    normalize,
    nextId,
    nodeById,
    laneById,
    buildingById,
    cameraById,
    connectedLanes,
    createNodeGroup,
    groupCenter,
    moveNodeGroup,
    connectNodeGroups,
    deleteNodeGroup,
    convertNodeToGroup,
    laneKey,
    lanePortKey,
    laneBundleKey,
    lanePath,
    pointBindingCandidates,
    laneSideAtNode,
    junctionSides,
    syncGroupMembership,
    buildLogic,
    exportPayload,
    toggleCalibrationLine,
    deepClone,
    lightweightClone
  };
})();
