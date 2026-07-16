(function () {
  "use strict";

  const G = window.RoadLogicModeler.geometry;
  const M = window.RoadLogicModeler.model;

  const C = {
    bg: "#111820",
    grid: "rgba(220,230,235,0.06)",
    world: "rgba(220,230,235,0.22)",
    lane: "#2f3f46",
    laneSelected: "#16b8a6",
    line: "rgba(255,255,255,0.72)",
    node: "#f8fafc",
    selected: "#22d3ee",
    labelBg: "rgba(17,24,32,0.86)",
    label: "#e5edf2",
    building: "rgba(127,139,149,0.18)",
    buildingLine: "#64748b",
    camera: "#f59e0b",
    cameraSoft: "rgba(245,158,11,0.14)",
    cell: "rgba(245,158,11,0.30)",
    group: "rgba(34,211,238,0.26)"
  };

  function render(ctx, state) {
    ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    if (state.showGrid) drawGrid(ctx, state);
    drawWorld(ctx, state);
    drawCameraCoverage(ctx, state);
    drawGroups(ctx, state);
    state.model.buildings.forEach((building) => drawBuilding(ctx, state, building));
    drawLanes(ctx, state);
    if (state.showNodes) state.model.nodes.forEach((node) => drawNode(ctx, state, node));
    state.model.cameras.forEach((camera) => drawCamera(ctx, state, camera));
    if (state.mode === "cameraPoint") drawCameraPointOverlay(ctx, state);
  }

  function drawGrid(ctx, state) {
    const step = Math.max(4, state.model.world.gridSize * state.view.zoom);
    const sx = ((state.view.x % step) + step) % step;
    const sy = ((state.view.y % step) + step) % step;
    ctx.save();
    ctx.strokeStyle = C.grid;
    ctx.lineWidth = 1;
    for (let x = sx; x < ctx.canvas.width; x += step) line(ctx, x, 0, x, ctx.canvas.height);
    for (let y = sy; y < ctx.canvas.height; y += step) line(ctx, 0, y, ctx.canvas.width, y);
    ctx.restore();
  }

  function drawWorld(ctx, state) {
    const a = w2s(state, { x: 0, y: 0 });
    const b = w2s(state, { x: state.model.world.width, y: state.model.world.height });
    ctx.save();
    ctx.setLineDash([8, 6]);
    ctx.strokeStyle = C.world;
    ctx.strokeRect(a.x, a.y, b.x - a.x, b.y - a.y);
    ctx.restore();
  }

  function drawGroups(ctx, state) {
    state.model.laneEndpointGroups.forEach((group) => {
      const nodes = group.nodeIds.map((id) => M.nodeById(state.model, id)).filter(Boolean);
      if (!nodes.length) return;
      const center = nodes.reduce((acc, node) => ({ x: acc.x + node.x / nodes.length, y: acc.y + node.y / nodes.length }), { x: 0, y: 0 });
      const cp = w2s(state, center);
      const r = Math.max(18, ...nodes.map((node) => G.distance(w2s(state, node), cp) + 14));
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = C.group;
      ctx.lineWidth = isSelected(state, "group", group.id) ? 3 : 1.5;
      ctx.beginPath();
      ctx.arc(cp.x, cp.y, r, 0, Math.PI * 2);
      ctx.stroke();
      ctx.restore();
    });
  }

  function drawCameraCoverage(ctx, state) {
    state.model.cameras.forEach((camera) => {
      const p = w2s(state, camera);
      const r = camera.range * state.view.zoom;
      const dir = camera.direction * Math.PI / 180;
      const half = camera.fov * Math.PI / 360;
      ctx.save();
      ctx.fillStyle = C.cameraSoft;
      ctx.beginPath();
      ctx.moveTo(p.x, p.y);
      ctx.arc(p.x, p.y, r, dir - half, dir + half);
      ctx.closePath();
      ctx.fill();
      ctx.fillStyle = C.cell;
      (camera.coverage.gridCells || []).forEach((cell) => {
        const q = w2s(state, { x: cell[0] * state.model.world.gridSize, y: cell[1] * state.model.world.gridSize });
        const s = state.model.world.gridSize * state.view.zoom;
        ctx.fillRect(q.x, q.y, s, s);
      });
      ctx.restore();
    });
  }

  function drawLanes(ctx, state) {
    const bundles = new Map();
    state.model.lanes.forEach((lane) => {
      const key = M.laneBundleKey(state.model, lane);
      if (!bundles.has(key)) bundles.set(key, []);
      bundles.get(key).push(lane);
    });
    bundles.forEach((lanes) => {
      lanes.sort((a, b) => a.renderOrder - b.renderOrder || a.id.localeCompare(b.id));
      lanes.forEach((lane, i) => drawLane(ctx, state, lane, i - (lanes.length - 1) / 2, bundleStartId(state, lanes), lanes.length > 1));
      drawBundleLines(ctx, state, lanes);
    });
  }

  function drawLane(ctx, state, lane, offsetIndex, startId, collapseGroups) {
    const base = laneScreenPath(state, lane, startId, collapseGroups);
    if (base.length < 2) return;
    const width = lane.width * state.view.zoom;
    const path = G.offsetPolyline(base, offsetIndex * width);
    const selected = isSelected(state, "lane", lane.id);
    const endpoint1AtStart = lane.endpoint1 === startId || M.lanePortKey(state.model, lane.endpoint1) === startId;
    const forwardReversed = endpoint1AtStart ? lane.direction === "2-1" : lane.direction === "1-2";
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = selected ? C.laneSelected : C.lane;
    ctx.lineWidth = width;
    polyline(ctx, path);
    drawLaneEdge(ctx, G.offsetPolyline(path, -width / 2), lane.leftLineStyle);
    drawLaneEdge(ctx, G.offsetPolyline(path, width / 2), lane.rightLineStyle);
    drawArrow(ctx, path, endpoint1AtStart ? 0.28 : 0.72, lane.endpoint1Arrow, forwardReversed, width);
    drawArrow(ctx, path, endpoint1AtStart ? 0.72 : 0.28, lane.endpoint2Arrow, forwardReversed, width);
    if (state.showLabels) {
      const p = G.pointOnPolyline(path, 0.5);
      label(ctx, p.x, p.y - 16, lane.name || lane.id, selected);
    }
    ctx.restore();
  }

  function drawBundleLines(ctx, state, lanes) {
    if (lanes.length < 2) return;
    const base = laneScreenPath(state, lanes[0], bundleStartId(state, lanes), true);
    const width = lanes[0].width * state.view.zoom;
    lanes.slice(0, -1).forEach((lane, i) => {
      const offset = (i - (lanes.length - 1) / 2 + 0.5) * width;
      drawLaneEdge(ctx, G.offsetPolyline(base, offset), combineLine(lane.rightLineStyle, lanes[i + 1].leftLineStyle));
    });
  }

  function laneScreenPath(state, lane, startId, collapseGroups = false) {
    let points = M.lanePath(state.model, lane).map((point) => w2s(state, point));
    if (collapseGroups && points.length >= 2) {
      const endpoint1 = M.nodeById(state.model, lane.endpoint1);
      const endpoint2 = M.nodeById(state.model, lane.endpoint2);
      const group1 = endpoint1?.groupId && state.model.laneEndpointGroups.find((group) => group.id === endpoint1.groupId);
      const group2 = endpoint2?.groupId && state.model.laneEndpointGroups.find((group) => group.id === endpoint2.groupId);
      if (group1) points[0] = w2s(state, M.groupCenter(state.model, group1));
      if (group2) points[points.length - 1] = w2s(state, M.groupCenter(state.model, group2));
    }
    if (startId && lane.endpoint1 !== startId && M.lanePortKey(state.model, lane.endpoint1) !== startId) points = points.slice().reverse();
    if (lane.interpolation === "quadratic" && points.length >= 3) return sampleQuadratic(points[0], points[1], points[points.length - 1], 24);
    if (lane.interpolation === "cubic" && points.length >= 4) return sampleCubic(points[0], points[1], points[2], points[points.length - 1], 32);
    return points;
  }

  function bundleStartId(state, lanes) {
    const lane = lanes[0];
    const portCenter = (nodeId) => {
      const node = M.nodeById(state.model, nodeId);
      const group = node?.groupId && state.model.laneEndpointGroups.find((item) => item.id === node.groupId);
      return group ? M.groupCenter(state.model, group) : node;
    };
    const a = portCenter(lane.endpoint1);
    const b = portCenter(lane.endpoint2);
    const endpoint1First = !a || !b || a.x < b.x || (a.x === b.x && a.y <= b.y);
    return M.lanePortKey(state.model, endpoint1First ? lane.endpoint1 : lane.endpoint2);
  }

  function sampleQuadratic(a, c, b, count) {
    return Array.from({ length: count + 1 }, (_, i) => {
      const t = i / count;
      const mt = 1 - t;
      return { x: mt * mt * a.x + 2 * mt * t * c.x + t * t * b.x, y: mt * mt * a.y + 2 * mt * t * c.y + t * t * b.y };
    });
  }

  function sampleCubic(a, c1, c2, b, count) {
    return Array.from({ length: count + 1 }, (_, i) => {
      const t = i / count;
      const mt = 1 - t;
      return {
        x: mt ** 3 * a.x + 3 * mt * mt * t * c1.x + 3 * mt * t * t * c2.x + t ** 3 * b.x,
        y: mt ** 3 * a.y + 3 * mt * mt * t * c1.y + 3 * mt * t * t * c2.y + t ** 3 * b.y
      };
    });
  }

  function drawLaneEdge(ctx, points, style) {
    if (!style || style === "none") return;
    ctx.save();
    ctx.strokeStyle = C.line;
    ctx.lineWidth = 1.6;
    ctx.setLineDash(style === "dashed" ? [9, 7] : []);
    polyline(ctx, points);
    ctx.restore();
  }

  function combineLine(a, b) {
    if (a === "none" && b === "none") return "none";
    if (a === "none") return b;
    if (b === "none") return a;
    if (a === "dashed" || b === "dashed") return "dashed";
    return "solid";
  }

  function drawArrow(ctx, points, ratio, arrow, reverse, width) {
    if (!arrow || arrow === "none") return;
    const seg = G.segmentAt(points, ratio);
    if (!seg) return;
    const p = G.pointOnPolyline(points, ratio);
    const a = reverse ? seg.b : seg.a;
    const b = reverse ? seg.a : seg.b;
    const size = Math.max(10, Math.min(18, width * 0.45));
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(Math.atan2(b.y - a.y, b.x - a.x));
    if (arrow === "backward") ctx.rotate(Math.PI);
    if (arrow === "left") ctx.rotate(-Math.PI / 2);
    if (arrow === "right") ctx.rotate(Math.PI / 2);
    ctx.strokeStyle = "#fff";
    ctx.fillStyle = "#fff";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(-size, 0);
    ctx.lineTo(size, 0);
    if (arrow === "forward_left") {
      ctx.moveTo(0, 0);
      ctx.quadraticCurveTo(size * 0.2, -size * 0.65, size * 0.9, -size * 0.8);
    }
    if (arrow === "forward_right") {
      ctx.moveTo(0, 0);
      ctx.quadraticCurveTo(size * 0.2, size * 0.65, size * 0.9, size * 0.8);
    }
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(size + 1, 0);
    ctx.lineTo(size - 7, -5);
    ctx.lineTo(size - 7, 5);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  function drawNode(ctx, state, node) {
    const p = w2s(state, node);
    const selected = isSelected(state, "node", node.id);
    const lanes = M.connectedLanes(state.model, node.id);
    ctx.save();
    ctx.strokeStyle = selected ? C.selected : "#77848d";
    ctx.lineWidth = selected ? 3 : 1.5;
    if (node.type === "junction") drawJunction(ctx, state, node, p, selected);
    else if (node.type === "boundary") drawBoundary(ctx, state, node, lanes);
    else drawPointNode(ctx, p, node.type, selected);
    if (state.showLabels && node.type !== "junction" && (node.type !== "lane_point" || selected)) {
      label(ctx, p.x, p.y + 24, `${node.name} · H${node.z}`, selected);
    }
    ctx.restore();
  }

  function drawJunction(ctx, state, node, p, selected) {
    const sides = M.junctionSides(state.model, node.id);
    const { w, h } = junctionSize(sides);
    ctx.fillStyle = selected ? "#dff9fb" : "#f8fafc";
    roundRect(ctx, p.x - w / 2, p.y - h / 2, w, h, 8);
    ctx.fill();
    ctx.stroke();
    if (!state.showLabels) return;
    ctx.save();
    ctx.font = "10px Segoe UI, Microsoft YaHei, Arial";
    ctx.fillStyle = "#18212a";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(node.name, p.x, p.y);
    drawJunctionSideText(ctx, state, sides.north, "north", p, w, h);
    drawJunctionSideText(ctx, state, sides.south, "south", p, w, h);
    drawJunctionSideText(ctx, state, sides.west, "west", p, w, h);
    drawJunctionSideText(ctx, state, sides.east, "east", p, w, h);
    ctx.restore();
  }

  function drawJunctionSideText(ctx, state, laneIds, side, p, w, h) {
    if (!laneIds.length) return;
    const names = laneIds.map((id) => M.laneById(state.model, id)?.name || id);
    const isHorizontal = side === "north" || side === "south";
    const span = isHorizontal ? w - 22 : h - 18;
    names.forEach((name, index) => {
      const t = (index + 1) / (names.length + 1);
      let x = p.x;
      let y = p.y;
      if (side === "north") { x = p.x - span / 2 + span * t; y = p.y - h / 2 + 10; }
      if (side === "south") { x = p.x - span / 2 + span * t; y = p.y + h / 2 - 10; }
      if (side === "west") { x = p.x - w / 2 + 15; y = p.y - span / 2 + span * t; }
      if (side === "east") { x = p.x + w / 2 - 15; y = p.y - span / 2 + span * t; }
      ctx.fillText(name.length > 5 ? `${name.slice(0, 4)}...` : name, x, y);
    });
  }

  function drawBoundary(ctx, state, node, lanes) {
    const p = w2s(state, node);
    const len = Math.max(34, lanes.length * 22);
    const angle = boundaryLineAngle(state, node, lanes);
    const whisker = 7;
    ctx.strokeStyle = "#d7dde2";
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(angle);
    ctx.beginPath();
    ctx.moveTo(-len / 2, 0);
    ctx.lineTo(len / 2, 0);
    ctx.moveTo(-len / 2, -whisker);
    ctx.lineTo(-len / 2, whisker);
    ctx.moveTo(len / 2, -whisker);
    ctx.lineTo(len / 2, whisker);
    ctx.stroke();
    ctx.restore();
  }

  function boundaryLineAngle(state, node, lanes) {
    if (!lanes.length) return 0;
    const vectors = lanes.map((lane) => {
      const other = M.nodeById(state.model, lane.endpoint1 === node.id ? lane.endpoint2 : lane.endpoint1);
      if (!other) return null;
      return { x: other.x - node.x, y: other.y - node.y };
    }).filter(Boolean);
    const avg = vectors.reduce((acc, v) => ({ x: acc.x + v.x, y: acc.y + v.y }), { x: 0, y: 0 });
    return Math.atan2(avg.y, avg.x) + Math.PI / 2;
  }

  function drawPointNode(ctx, p, type, selected) {
    const radius = type === "building_anchor" ? 8 : 6;
    ctx.beginPath();
    ctx.fillStyle = selected ? C.selected : (type === "lane_point" ? "#9fb0ba" : C.node);
    ctx.arc(p.x, p.y, selected ? radius + 2 : radius, 0, Math.PI * 2);
    ctx.fill();
    if (type === "lane_point") {
      ctx.strokeStyle = selected ? C.selected : "rgba(34,211,238,0.55)";
      ctx.lineWidth = selected ? 3 : 1.5;
    }
    ctx.stroke();
  }

  function drawBuilding(ctx, state, building) {
    const p = w2s(state, building);
    const w = building.width * state.view.zoom;
    const h = building.height * state.view.zoom;
    const selected = isSelected(state, "building", building.id);
    ctx.save();
    ctx.fillStyle = selected ? "rgba(34,211,238,0.14)" : C.building;
    ctx.strokeStyle = selected ? C.selected : C.buildingLine;
    ctx.lineWidth = selected ? 3 : 1.5;
    roundRect(ctx, p.x - w / 2, p.y - h / 2, w, h, 6);
    ctx.fill();
    ctx.stroke();
    if (state.showLabels) label(ctx, p.x, p.y + h / 2 + 16, building.name, selected);
    ctx.restore();
  }

  function drawCamera(ctx, state, camera) {
    const p = w2s(state, camera);
    const selected = isSelected(state, "camera", camera.id);
    if (selected) drawCameraStructure(ctx, state, camera, p);
    ctx.save();
    ctx.translate(p.x, p.y);
    ctx.rotate(camera.direction * Math.PI / 180);
    ctx.fillStyle = selected ? C.selected : C.camera;
    ctx.beginPath();
    ctx.moveTo(15, 0);
    ctx.lineTo(-10, -9);
    ctx.lineTo(-10, 9);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    if (state.showLabels) label(ctx, p.x, p.y + 24, `${camera.name}·H${camera.height ?? 500}`, selected);
  }

  function drawCameraStructure(ctx, state, camera, origin) {
    const endpoint = w2s(state, G.cameraRangePoint(camera));
    const range = camera.range * state.view.zoom;
    const direction = camera.direction * Math.PI / 180;
    const halfFov = camera.fov * Math.PI / 360;
    ctx.save();
    ctx.strokeStyle = "rgba(34,211,238,0.9)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 5]);
    line(ctx, origin.x, origin.y, endpoint.x, endpoint.y);
    ctx.beginPath();
    ctx.arc(origin.x, origin.y, range, direction - halfFov, direction + halfFov);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = C.bg;
    ctx.strokeStyle = C.selected;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(endpoint.x, endpoint.y, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(endpoint.x, endpoint.y, 3, 0, Math.PI * 2);
    ctx.fillStyle = C.selected;
    ctx.fill();
    ctx.restore();
  }

  function drawCameraPointOverlay(ctx, state) {
    const cam = state.selected?.type === "camera" ? M.cameraById(state.model, state.selected.id) : null;
    ctx.save();
    ctx.fillStyle = "rgba(8,12,18,0.5)";
    ctx.fillRect(0, 0, ctx.canvas.width, ctx.canvas.height);
    const step = Math.max(4, state.model.world.gridSize * state.view.zoom);
    const sx = ((state.view.x % step) + step) % step;
    const sy = ((state.view.y % step) + step) % step;
    ctx.strokeStyle = "rgba(34,211,238,0.12)";
    ctx.lineWidth = 1;
    for (let x = sx; x < ctx.canvas.width; x += step) line(ctx, x, 0, x, ctx.canvas.height);
    for (let y = sy; y < ctx.canvas.height; y += step) line(ctx, 0, y, ctx.canvas.width, y);
    if (!cam) { ctx.restore(); return; }
    const correspondences = correspondenceBindings(state, cam);
    if (correspondences.length >= 2) {
      ctx.strokeStyle = "rgba(34,211,238,0.5)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      const first = w2s(state, correspondences[0].binding.worldPoint);
      ctx.moveTo(first.x, first.y);
      for (let i = 1; i < correspondences.length; i += 1) {
        const sp = w2s(state, correspondences[i].binding.worldPoint);
        ctx.lineTo(sp.x, sp.y);
      }
      ctx.stroke();
    }
    correspondences.forEach(({ point, binding, label: pointLabel }, index) => {
      const sp = w2s(state, binding.worldPoint);
      const selected = state.selectedImagePointId === binding.imagePointId;
      ctx.fillStyle = selected ? C.selected : C.camera;
      ctx.strokeStyle = "#111820";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(sp.x, sp.y, 7, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "11px Segoe UI, Microsoft YaHei, Arial";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(index + 1), sp.x, sp.y);
      label(ctx, sp.x, sp.y - 20, `${pointLabel} · H${binding.worldPoint.height ?? 500}`, selected, 11);
    });
    ctx.restore();
  }

  function correspondenceBindings(state, camera) {
    const calibration = state.model.cameraCalibrations.find((item) => item.id === camera.calibrationId);
    const points = calibration?.points || [];
    const byId = new Map(points.map((point) => [point.id, point]));
    return (camera.pointBindings || [])
      .filter((binding) => binding.worldPoint)
      .map((binding) => ({
        binding,
        point: byId.get(binding.imagePointId) || null,
        label: byId.get(binding.imagePointId)?.name || binding.imagePointId
      }));
  }

  function hitTest(state, point) {
    if (state.selected?.type === "camera") {
      const selectedCamera = M.cameraById(state.model, state.selected.id);
      if (selectedCamera) {
        const handle = w2s(state, G.cameraRangePoint(selectedCamera));
        if (G.distance(point, handle) <= 14) return { type: "cameraHandle", id: selectedCamera.id };
      }
    }
    for (let i = state.model.cameras.length - 1; i >= 0; i -= 1) {
      if (G.distance(point, w2s(state, state.model.cameras[i])) <= 18) return { type: "camera", id: state.model.cameras[i].id };
    }
    for (let i = state.model.nodes.length - 1; i >= 0; i -= 1) {
      if (hitNode(state, state.model.nodes[i], point)) return { type: "node", id: state.model.nodes[i].id };
    }
    for (let i = state.model.buildings.length - 1; i >= 0; i -= 1) {
      const b = state.model.buildings[i];
      const p = w2s(state, b);
      if (Math.abs(point.x - p.x) <= b.width * state.view.zoom / 2 && Math.abs(point.y - p.y) <= b.height * state.view.zoom / 2) return { type: "building", id: b.id };
    }
    const laneLayouts = expandedLaneLayouts(state);
    for (let i = laneLayouts.length - 1; i >= 0; i -= 1) {
      const layout = laneLayouts[i];
      if (G.distanceToPolyline(point, layout.path) <= Math.max(12, layout.lane.width * state.view.zoom / 2)) return { type: "lane", id: layout.lane.id };
    }
    return null;
  }

  function expandedLaneLayouts(state) {
    const bundles = new Map();
    state.model.lanes.forEach((lane) => {
      const key = M.laneBundleKey(state.model, lane);
      if (!bundles.has(key)) bundles.set(key, []);
      bundles.get(key).push(lane);
    });
    const layouts = [];
    bundles.forEach((lanes) => {
      lanes.sort((a, b) => a.renderOrder - b.renderOrder || a.id.localeCompare(b.id));
      const startId = bundleStartId(state, lanes);
      lanes.forEach((lane, i) => {
        const width = lane.width * state.view.zoom;
        layouts.push({ lane, path: G.offsetPolyline(laneScreenPath(state, lane, startId, lanes.length > 1), (i - (lanes.length - 1) / 2) * width) });
      });
    });
    return layouts;
  }

  function hitNode(state, node, point) {
    const p = w2s(state, node);
    if (node.type === "junction") {
      const size = junctionSize(M.junctionSides(state.model, node.id));
      return Math.abs(point.x - p.x) <= size.w / 2 + 4 && Math.abs(point.y - p.y) <= size.h / 2 + 4;
    }
    if (node.type === "boundary") return G.distance(point, p) <= 22;
    return G.distance(point, p) <= (node.type === "building_anchor" ? 14 : 12);
  }

  function junctionSize(sides) {
    const topBottom = Math.max(sides.north.length, sides.south.length);
    const leftRight = Math.max(sides.west.length, sides.east.length);
    return {
      w: Math.max(76, topBottom * 44 + 28),
      h: Math.max(54, leftRight * 28 + 24)
    };
  }

  function w2s(state, p) {
    return { x: state.view.x + p.x * state.view.zoom, y: state.view.y + p.y * state.view.zoom };
  }

  function s2w(state, p) {
    return { x: (p.x - state.view.x) / state.view.zoom, y: (p.y - state.view.y) / state.view.zoom };
  }

  function isSelected(state, type, id) {
    return state.selected && state.selected.type === type && state.selected.id === id;
  }

  function polyline(ctx, points) {
    if (points.length < 2) return;
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);
    for (let i = 1; i < points.length; i += 1) ctx.lineTo(points[i].x, points[i].y);
    ctx.stroke();
  }

  function line(ctx, x1, y1, x2, y2) {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    ctx.lineTo(x2, y2);
    ctx.stroke();
  }

  function roundRect(ctx, x, y, w, h, r) {
    if (ctx.roundRect) {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, r);
      return;
    }
    ctx.beginPath();
    ctx.rect(x, y, w, h);
  }

  function label(ctx, x, y, text, selected, size) {
    const s = size || 12;
    const value = String(text || "");
    ctx.save();
    ctx.font = `${s}px Segoe UI, Microsoft YaHei, Arial`;
    const display = value.length > 18 ? `${value.slice(0, 17)}...` : value;
    const w = ctx.measureText(display).width + 10;
    ctx.fillStyle = selected ? "rgba(34,211,238,0.92)" : C.labelBg;
    ctx.fillRect(x - w / 2, y - 10, w, 20);
    ctx.fillStyle = C.label;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(display, x, y);
    ctx.restore();
  }

  window.RoadLogicModeler.renderer = { render, hitTest, worldToScreen: w2s, screenToWorld: s2w, laneScreenPath, correspondenceBindings };
})();
