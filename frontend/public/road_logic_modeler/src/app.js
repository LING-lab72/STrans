(function () {
  "use strict";

  const G = window.RoadLogicModeler.geometry;
  const M = window.RoadLogicModeler.model;
  const R = window.RoadLogicModeler.renderer;

  const state = {
    mode: "select",
    selected: null,
    drag: null,
    laneStart: null,
    showGrid: true,
    snap: true,
    showNodes: true,
    showLabels: true,
    nodeType: "junction",
    groupNodeCount: 2,
    groupSpacing: 36,
    groupAngle: 90,
    view: { x: 80, y: 70, zoom: 0.75 },
    model: M.createModel(),
    selectedImagePointId: "",
    selectedImageLineId: "",
    zoomLineStartId: "",
    zoomLineConnectActive: false,
    zoomCleanup: null
  };

  const el = {};
  const history = [];

  function init() {
    [
      "canvas", "modeSelect", "modeNode", "modeGroup", "modeLane", "modeBuilding", "modeCamera", "modeCameraPoint",
      "nodeType", "status", "toggleGrid", "toggleSnap", "toggleNodes", "toggleLabels", "gridSize",
      "groupNodeCount", "groupSpacing", "groupAngle",
      "fitView", "deleteSelected", "convertToGroup", "refreshJson", "downloadJson", "importJsonFile", "nodeCount", "laneCount",
      "groupCount", "buildingCount", "cameraCount", "properties", "cameraImagePanel", "entityList", "jsonOutput"
    ].forEach((id) => { el[id] = document.getElementById(id); });
    el.nodeType.innerHTML = M.NODE_TYPES.map(([v, t]) => `<option value="${v}">${t}</option>`).join("");
    bindEvents();
    resize();
    fitView();
    sync(false);
    updateJson();
  }

  function bindEvents() {
    window.addEventListener("resize", resize);
    el.canvas.addEventListener("pointerdown", pointerDown);
    el.canvas.addEventListener("pointermove", pointerMove);
    el.canvas.addEventListener("pointerup", pointerUp);
    el.canvas.addEventListener("wheel", wheel, { passive: false });
    el.modeSelect.addEventListener("click", () => mode("select"));
    el.modeNode.addEventListener("click", () => mode("node"));
    el.modeGroup.addEventListener("click", () => mode("group"));
    el.modeLane.addEventListener("click", () => mode("lane"));
    el.modeBuilding.addEventListener("click", () => mode("building"));
    el.modeCamera.addEventListener("click", () => mode("camera"));
    el.modeCameraPoint.addEventListener("click", () => mode("cameraPoint"));
    el.nodeType.addEventListener("change", () => { state.nodeType = el.nodeType.value; });
    el.groupNodeCount.addEventListener("change", () => { state.groupNodeCount = Math.max(1, Math.min(12, Number(el.groupNodeCount.value) || 2)); });
    el.groupSpacing.addEventListener("change", () => { state.groupSpacing = Math.max(4, Number(el.groupSpacing.value) || 36); });
    el.groupAngle.addEventListener("change", () => { state.groupAngle = Number(el.groupAngle.value) || 0; });
    el.toggleGrid.addEventListener("click", () => toggle("showGrid", el.toggleGrid));
    el.toggleSnap.addEventListener("click", () => toggle("snap", el.toggleSnap));
    el.toggleNodes.addEventListener("click", () => toggle("showNodes", el.toggleNodes));
    el.toggleLabels.addEventListener("click", () => toggle("showLabels", el.toggleLabels));
    el.gridSize.addEventListener("change", () => { remember(); state.model.world.gridSize = Math.max(5, Number(el.gridSize.value || 20)); sync(); });
    el.fitView.addEventListener("click", fitView);
    el.deleteSelected.addEventListener("click", deleteSelected);
    el.convertToGroup.addEventListener("click", convertSelectedNodeToGroup);
    el.refreshJson.addEventListener("click", () => { updateJson(); status("JSON 已刷新"); });
    el.downloadJson.addEventListener("click", downloadJson);
    el.importJsonFile.addEventListener("change", importJsonFile);
    el.jsonOutput.addEventListener("change", importJson);
    window.addEventListener("keydown", keydown);
  }

  function mode(next) {
    if (next === "cameraPoint" && state.mode === "cameraPoint") next = "select";
    if (next !== "cameraPoint") closeZoomCalibration();
    state.mode = next;
    state.laneStart = null;
    [el.modeSelect, el.modeNode, el.modeGroup, el.modeLane, el.modeBuilding, el.modeCamera, el.modeCameraPoint].forEach((btn) => btn.classList.remove("active"));
    ({ select: el.modeSelect, node: el.modeNode, group: el.modeGroup, lane: el.modeLane, building: el.modeBuilding, camera: el.modeCamera, cameraPoint: el.modeCameraPoint })[next].classList.add("active");
    status({
      select: "选择/拖动元素；空白处拖动画布",
      node: "点击添加端点；靠近建筑物边缘会变为建筑物端点",
      group: "点击放置道路截面节点组；在选择模式拖动组中心可整体移动",
      lane: "依次点击两个道路节点生成车道",
      building: "按下并拖动确定建筑物矩形",
      camera: "按下并拖动设置摄像头位置、方向和范围；拖动范围端点可调整",
      cameraPoint: "标点层已开启；选中画面点后在网格上点击放置，重复点击“标点”或按 Esc 结束"
    }[next]);
    sync(false);
  }

  function pointerDown(e) {
    el.canvas.setPointerCapture(e.pointerId);
    const screen = pointer(e);
    const rawWorld = clampWorld(R.screenToWorld(state, screen));
    const world = clampWorld(snapped(rawWorld));
    const hit = R.hitTest(state, screen);

    if (hit?.type === "cameraHandle") {
      remember();
      select("camera", hit.id);
      state.drag = { type: "cameraRange", id: hit.id };
      sync(false);
      return;
    }
    if (state.mode === "node") {
      remember();
      const node = addNode(world, state.nodeType);
      snapNodeToBuilding(node);
      select("node", node.id);
      sync();
      return;
    }
    if (state.mode === "group") {
      remember();
      const group = M.createNodeGroup(state.model, world, { count: state.groupNodeCount, spacing: state.groupSpacing, angle: state.groupAngle });
      select("group", group.id);
      status(`已创建 ${group.nodeIds.length} 节点道路截面`);
      sync();
      return;
    }
    if (state.mode === "building") {
      remember();
      const building = addBuilding(world, 1, 1);
      select("building", building.id);
      state.drag = { type: "buildingCreate", id: building.id, start: world };
      sync(false);
      return;
    }
    if (state.mode === "camera") {
      if (hit?.type === "camera") {
        select("camera", hit.id);
        const camera = entity("camera", hit.id);
        state.drag = { type: "camera", id: hit.id, start: screen, base: { x: camera.x, y: camera.y }, saved: false };
      } else if (!hit && state.selected?.type === "camera" && state.selectedImagePointId) {
        remember();
        bindImagePointToGrid(M.cameraById(state.model, state.selected.id), state.selectedImagePointId, world);
      } else if (!hit && state.selected?.type === "camera" && e.shiftKey) {
        remember();
        toggleCameraCell(M.cameraById(state.model, state.selected.id), world);
      } else if (!hit) {
        remember();
        const camera = addCamera(world);
        camera.range = state.model.world.gridSize;
        select("camera", camera.id);
        state.drag = { type: "cameraCreate", id: camera.id, origin: { x: camera.x, y: camera.y } };
      }
      sync(false);
      return;
    }
    if (state.mode === "cameraPoint") {
      if (!state.selected || state.selected.type !== "camera") {
        status("请先选择一个摄像头");
        sync(false);
        return;
      }
      const camera = entity("camera", state.selected.id);
      if (!camera) return;
      const hitId = findCorrespondenceHit(camera, screen);
      if (hitId) {
        state.selectedImagePointId = hitId;
        sync(false);
        return;
      }
      if (!state.selectedImagePointId) {
        status("请先在画面标定中选择一个画面点");
        sync(false);
        return;
      }
      remember();
      placeCorrespondencePoint(camera, state.selectedImagePointId, world);
      sync(false);
      return;
    }
    if (state.mode === "lane") {
      if (!hit || hit.type !== "node") {
        status("请选择两个道路节点直接连接");
        return;
      }
      if (!state.laneStart) {
        state.laneStart = { type: hit.type, id: hit.id };
        select(hit.type, hit.id);
        status(`已选择${hit.type === "group" ? "节点组" : "端点"} 1`);
      } else if (state.laneStart.id !== hit.id || state.laneStart.type !== hit.type) {
        remember();
        let created = [];
        if (state.laneStart.type === "group" && hit.type === "group") created = M.connectNodeGroups(state.model, state.laneStart.id, hit.id);
        else if (state.laneStart.type === "node" && hit.type === "node") created = [addLane(state.laneStart.id, hit.id)];
        else status("请使用端点连接端点，或节点组连接节点组");
        state.laneStart = null;
        if (created.length) {
          select(created.length === 1 ? "lane" : "group", created.length === 1 ? created[0].id : hit.id);
          status(`已创建 ${created.length} 条车道`);
        }
      }
      sync();
      return;
    }

    if (hit) {
      select(hit.type, hit.id);
      if (hit.type === "group") {
        const center = M.groupCenter(state.model, entity("group", hit.id));
        state.drag = center ? { type: "group", id: hit.id, start: screen, base: center, saved: false } : null;
        sync();
        return;
      }
      const item = entity(hit.type, hit.id);
      state.drag = item && "x" in item ? { type: hit.type, id: hit.id, start: screen, base: { x: item.x, y: item.y }, saved: false } : null;
    } else {
      state.selected = null;
      state.drag = { type: "pan", start: screen, view: { ...state.view } };
    }
    sync();
  }

  function pointerMove(e) {
    if (!state.drag) return;
    const screen = pointer(e);
    const rawWorld = clampWorld(R.screenToWorld(state, screen));
    const world = clampWorld(snapped(rawWorld));
    if (state.drag.type === "pan") {
      state.view.x = state.drag.view.x + screen.x - state.drag.start.x;
      state.view.y = state.drag.view.y + screen.y - state.drag.start.y;
      draw();
      return;
    }
    if (state.drag.type === "buildingCreate") {
      resizeBuilding(entity("building", state.drag.id), state.drag.start, world);
      draw();
      return;
    }
    if (state.drag.type === "cameraCreate" || state.drag.type === "cameraRange") {
      const camera = entity("camera", state.drag.id);
      if (!camera) return;
      const pose = G.cameraPoseFromPoints(camera, rawWorld, state.model.world.gridSize);
      camera.direction = pose.direction;
      camera.range = pose.range;
      draw();
      return;
    }
    if (state.drag.type === "group") {
      if (!state.drag.saved) { remember(); state.drag.saved = true; }
      const center = {
        x: state.drag.base.x + (screen.x - state.drag.start.x) / state.view.zoom,
        y: state.drag.base.y + (screen.y - state.drag.start.y) / state.view.zoom
      };
      M.moveNodeGroup(state.model, state.drag.id, state.snap ? snapped(center) : center);
      draw();
      return;
    }
    const item = entity(state.drag.type, state.drag.id);
    if (!item) return;
    if (!state.drag.saved) {
      remember();
      state.drag.saved = true;
    }
    item.x = G.clamp(state.drag.base.x + (screen.x - state.drag.start.x) / state.view.zoom, 0, state.model.world.width);
    item.y = G.clamp(state.drag.base.y + (screen.y - state.drag.start.y) / state.view.zoom, 0, state.model.world.height);
    if (state.snap) {
      const p = snapped(item);
      item.x = p.x;
      item.y = p.y;
    }
    if (state.drag.type === "node") snapNodeToBuilding(item);
    if (state.drag.type === "building") refreshAnchors(item);
    draw();
  }

  function pointerUp(e) {
    state.drag = null;
    try { el.canvas.releasePointerCapture(e.pointerId); } catch (_) {}
    sync();
  }

  function wheel(e) {
    e.preventDefault();
    const p = pointer(e);
    const before = R.screenToWorld(state, p);
    state.view.zoom = G.clamp(state.view.zoom * (e.deltaY < 0 ? 1.08 : 0.92), 0.25, 3);
    state.view.x = p.x - before.x * state.view.zoom;
    state.view.y = p.y - before.y * state.view.zoom;
    draw();
  }

  function keydown(e) {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target?.tagName)) return;
    if (e.key === "Delete" || e.key === "Backspace") deleteSelected();
    if (e.key === "Escape") mode("select");
    if (e.ctrlKey && e.key.toLowerCase() === "z") undo();
  }

  function addNode(point, type) {
    const node = { id: M.nextId("node", state.model.nodes), name: `端点 ${state.model.nodes.length + 1}`, type, x: point.x, y: point.y, z: 0, buildingId: "", groupId: "" };
    state.model.nodes.push(node);
    return node;
  }

  function addLane(endpoint1, endpoint2) {
    const lane = {
      id: M.nextId("lane", state.model.lanes),
      name: `车道 ${state.model.lanes.length + 1}`,
      endpoint1,
      endpoint2,
      height: null,
      width: 28,
      interpolation: "line",
      controlPoints: [],
      direction: "1-2",
      endpoint1Arrow: "none",
      endpoint2Arrow: "forward",
      leftLineStyle: "solid",
      rightLineStyle: "solid",
      renderOrder: state.model.lanes.filter((item) => M.laneKey(item) === [endpoint1, endpoint2].sort().join("::")).length
    };
    state.model.lanes.push(lane);
    return lane;
  }

  function addBuilding(point, width, height) {
    const building = { id: M.nextId("building", state.model.buildings), name: `建筑物 ${state.model.buildings.length + 1}`, x: point.x, y: point.y, width, height, anchorNodeIds: [] };
    state.model.buildings.push(building);
    return building;
  }

  function addCamera(point) {
    const preset = M.CAMERA_PRESETS[0];
    const camera = { id: M.nextId("cam", state.model.cameras), name: `摄像头 ${state.model.cameras.length + 1}`, place: preset.place, x: point.x, y: point.y, direction: 0, fov: 60, range: 240, streamPresetId: preset.id, rtspUrl: preset.url, calibrationId: "", pointBindings: [], coverage: { gridCells: [] } };
    state.model.cameras.push(camera);
    return camera;
  }

  function resizeBuilding(building, start, end) {
    if (!building) return;
    building.x = (start.x + end.x) / 2;
    building.y = (start.y + end.y) / 2;
    building.width = Math.max(state.model.world.gridSize, Math.abs(end.x - start.x));
    building.height = Math.max(state.model.world.gridSize, Math.abs(end.y - start.y));
  }

  function snapNodeToBuilding(node) {
    state.model.buildings.forEach((building) => {
      building.anchorNodeIds = (building.anchorNodeIds || []).filter((id) => id !== node.id);
    });
    if (node.type === "lane_point") {
      node.buildingId = "";
      return;
    }
    let best = null;
    state.model.buildings.forEach((building) => {
      const snap = G.nearestRectEdge(node, building);
      if (snap.distance <= state.model.world.gridSize * 0.8 && (!best || snap.distance < best.snap.distance)) best = { building, snap };
    });
    if (!best) {
      if (node.type === "building_anchor") node.buildingId = "";
      return;
    }
    node.type = "building_anchor";
    node.x = best.snap.x;
    node.y = best.snap.y;
    node.buildingId = best.building.id;
    best.building.anchorNodeIds = best.building.anchorNodeIds || [];
    if (!best.building.anchorNodeIds.includes(node.id)) best.building.anchorNodeIds.push(node.id);
  }

  function refreshAnchors(building) {
    (building.anchorNodeIds || []).forEach((id) => {
      const node = M.nodeById(state.model, id);
      if (!node) return;
      const snap = G.nearestRectEdge(node, building);
      node.x = snap.x;
      node.y = snap.y;
      node.type = "building_anchor";
      node.buildingId = building.id;
    });
  }

  function toggleCameraCell(camera, world) {
    if (!camera) return;
    if (world.x < 0 || world.y < 0 || world.x > state.model.world.width || world.y > state.model.world.height) return;
    const size = state.model.world.gridSize;
    const cell = [Math.floor(world.x / size), Math.floor(world.y / size)];
    const key = cell.join(",");
    camera.coverage.gridCells = camera.coverage.gridCells || [];
    const index = camera.coverage.gridCells.findIndex((item) => item.join(",") === key);
    if (index >= 0) camera.coverage.gridCells.splice(index, 1);
    else camera.coverage.gridCells.push(cell);
  }

  function bindImagePointToGrid(camera, imagePointId, world) {
    if (!camera) return;
    const size = state.model.world.gridSize;
    const cell = [Math.floor(world.x / size), Math.floor(world.y / size)];
    const gridCellId = `grid_${cell[0]}_${cell[1]}`;
    camera.pointBindings = (camera.pointBindings || []).filter((binding) => binding.imagePointId !== imagePointId);
    camera.pointBindings.push({ imagePointId, gridCellId, gridCell: cell });
    if (!(camera.coverage.gridCells || []).some((item) => item[0] === cell[0] && item[1] === cell[1])) camera.coverage.gridCells.push(cell);
    status(`${imagePointId} 已绑定 ${gridCellId}`);
  }

  function placeCorrespondencePoint(camera, imagePointId, world) {
    if (!camera) return;
    const existing = (camera.pointBindings || []).find((b) => b.imagePointId === imagePointId);
    const height = existing?.worldPoint?.height ?? camera.height ?? 500;
    const candidates = M.pointBindingCandidates(state.model, world);
    const candidate = chooseBindingCandidate(candidates);
    if (candidate === undefined) return;
    const binding = { imagePointId, worldPoint: { x: world.x, y: world.y, height } };
    if (candidate?.type === "node") binding.nodeId = candidate.id;
    if (candidate?.type === "lane") binding.laneId = candidate.id;
    if (candidate?.type === "building") binding.buildingId = candidate.id;
    camera.pointBindings = (camera.pointBindings || []).filter((b) => b.imagePointId !== imagePointId);
    camera.pointBindings.push(binding);
    status(`${imagePointId} 已绑定${candidate ? `：${candidate.label}` : `自由坐标 (${world.x}, ${world.y})`}`);
  }

  function chooseBindingCandidate(candidates) {
    if (!candidates.length) return null;
    if (candidates.length === 1) return candidates[0];
    const options = candidates.map((item, index) => `${index + 1}. ${item.label}`).join("\n");
    const answer = window.prompt(`该位置存在多个重叠元素，请输入序号：\n${options}\n0. 仅保存世界坐标`, "1");
    if (answer === null) return undefined;
    const index = Number(answer);
    if (index === 0) return null;
    return candidates[index - 1];
  }

  function findCorrespondenceHit(camera, screen) {
    if (!camera) return null;
    const bindings = (camera.pointBindings || []).filter((b) => b.worldPoint);
    for (const binding of bindings) {
      const sp = R.worldToScreen(state, binding.worldPoint);
      if (Math.hypot(screen.x - sp.x, screen.y - sp.y) <= 12) return binding.imagePointId;
    }
    return null;
  }

  function deleteCorrespondencePoint(camera, imagePointId) {
    if (!camera) return;
    camera.pointBindings = (camera.pointBindings || []).filter((b) => b.imagePointId !== imagePointId);
    status(`${imagePointId} 标点已删除`);
  }

  function createGroupFromSelectedNode() {
    remember();
    const nodeIds = state.selected?.type === "node" ? [state.selected.id] : [];
    const group = { id: M.nextId("group", state.model.laneEndpointGroups), name: `道路节点组 ${state.model.laneEndpointGroups.length + 1}`, nodeIds, order: "auto" };
    state.model.laneEndpointGroups.push(group);
    if (nodeIds[0]) M.nodeById(state.model, nodeIds[0]).groupId = group.id;
    select("group", group.id);
    sync();
  }

  function deleteSelected() {
    if (!state.selected) return;
    remember();
    const { type, id } = state.selected;
    if (type === "group") M.deleteNodeGroup(state.model, id);
    else {
      const col = collection(type);
      const index = col.findIndex((item) => item.id === id);
      if (index >= 0) col.splice(index, 1);
    }
    if (type === "node") {
      state.model.lanes = state.model.lanes.filter((lane) => lane.endpoint1 !== id && lane.endpoint2 !== id);
      state.model.laneEndpointGroups.forEach((group) => { group.nodeIds = group.nodeIds.filter((nodeId) => nodeId !== id); });
      state.model.buildings.forEach((building) => { building.anchorNodeIds = building.anchorNodeIds.filter((nodeId) => nodeId !== id); });
    }
    state.selected = null;
    sync();
  }

  function convertSelectedNodeToGroup() {
    if (state.selected?.type !== "node") {
      status("请先选择一个已连接车道的端点");
      return;
    }
    remember();
    const group = M.convertNodeToGroup(state.model, state.selected.id);
    if (!group) {
      history.pop();
      status("该端点没有可转换的车道连接");
      return;
    }
    select("group", group.id);
    status(`已将 ${group.nodeIds.length} 个车道连接转换为道路内节点`);
    sync();
  }

  function renderProperties() {
    if (!state.selected) {
      el.properties.innerHTML = '<div class="empty">未选中元素</div>';
      return;
    }
    const item = entity(state.selected.type, state.selected.id);
    if (!item) {
      state.selected = null;
      renderProperties();
      return;
    }
    if (state.selected.type === "node") nodeProps(item);
    if (state.selected.type === "lane") laneProps(item);
    if (state.selected.type === "building") buildingProps(item);
    if (state.selected.type === "camera") cameraProps(item);
    if (state.selected.type === "group") groupProps(item);
  }

  function nodeProps(node) {
    const bOpts = [["", "无"], ...state.model.buildings.map((b) => [b.id, `${b.id} ${b.name}`])];
    const gOpts = [["", "无"], ...state.model.laneEndpointGroups.map((g) => [g.id, `${g.id} ${g.name}`])];
    el.properties.innerHTML = `
      ${field("ID", "pId", node.id, true)}
      ${field("名称", "pName", node.name)}
      ${selectField("类型", "pType", node.type, M.NODE_TYPES)}
      ${num("X", "pX", node.x)}${num("Y", "pY", node.y)}${num("高度", "pZ", node.z)}
      ${selectField("连接建筑物", "pBuilding", node.buildingId || "", bOpts)}
      ${selectField("端点组", "pGroup", node.groupId || "", gOpts)}
    `;
    bind("pName", (v) => { node.name = v; });
    bind("pType", (v) => { node.type = v; snapNodeToBuilding(node); });
    bind("pX", (v) => { node.x = Number(v); snapNodeToBuilding(node); });
    bind("pY", (v) => { node.y = Number(v); snapNodeToBuilding(node); });
    bind("pZ", (v) => { node.z = Number(v) || 0; });
    bind("pBuilding", (v) => {
      node.buildingId = v;
      if (v) {
        const building = M.buildingById(state.model, v);
        if (building) {
          const snap = G.nearestRectEdge(node, building);
          node.x = snap.x; node.y = snap.y; node.type = "building_anchor";
          if (!building.anchorNodeIds.includes(node.id)) building.anchorNodeIds.push(node.id);
        }
      }
    });
    bind("pGroup", (v) => setNodeGroup(node, v));
  }

  function laneProps(lane) {
    const nOpts = state.model.nodes.map((node) => [node.id, `${node.id} ${node.name}`]);
    el.properties.innerHTML = `
      ${field("ID", "pId", lane.id, true)}
      ${field("名称", "pName", lane.name)}
      ${selectField("端点1", "pE1", lane.endpoint1, nOpts)}
      ${selectField("端点2", "pE2", lane.endpoint2, nOpts)}
      ${field("路面高度", "pH", lane.height ?? "")}
      ${num("车道宽", "pW", lane.width)}
      ${selectField("插值", "pInterp", lane.interpolation, M.INTERPOLATIONS)}
      ${selectField("方向", "pDir", lane.direction, M.DIRECTIONS)}
      ${selectField("端点1箭头", "pA1", lane.endpoint1Arrow, M.ARROWS)}
      ${selectField("端点2箭头", "pA2", lane.endpoint2Arrow, M.ARROWS)}
      ${selectField("左边线", "pL", lane.leftLineStyle, M.LINE_STYLES)}
      ${selectField("右边线", "pR", lane.rightLineStyle, M.LINE_STYLES)}
      ${num("展开顺序", "pOrder", lane.renderOrder)}
      ${area("控制点 JSON", "pCP", lane.controlPoints)}
    `;
    bind("pName", (v) => { lane.name = v; });
    bind("pE1", (v) => { lane.endpoint1 = v; });
    bind("pE2", (v) => { lane.endpoint2 = v; });
    bind("pH", (v) => { lane.height = v === "" ? null : Number(v); });
    bind("pW", (v) => { lane.width = Math.max(4, Number(v) || 28); });
    bind("pInterp", (v) => { lane.interpolation = v; });
    bind("pDir", (v) => { lane.direction = v; });
    bind("pA1", (v) => { lane.endpoint1Arrow = v; });
    bind("pA2", (v) => { lane.endpoint2Arrow = v; });
    bind("pL", (v) => { lane.leftLineStyle = v; });
    bind("pR", (v) => { lane.rightLineStyle = v; });
    bind("pOrder", (v) => { lane.renderOrder = Number(v) || 0; });
    bindJson("pCP", (v) => { lane.controlPoints = Array.isArray(v) ? v : []; });
  }

  function buildingProps(building) {
    el.properties.innerHTML = `${field("ID", "pId", building.id, true)}${field("名称", "pName", building.name)}${num("X", "pX", building.x)}${num("Y", "pY", building.y)}${num("宽", "pW", building.width)}${num("高", "pH", building.height)}${area("吸附端点", "pA", building.anchorNodeIds)}`;
    bind("pName", (v) => { building.name = v; });
    bind("pX", (v) => { building.x = Number(v) || 0; refreshAnchors(building); });
    bind("pY", (v) => { building.y = Number(v) || 0; refreshAnchors(building); });
    bind("pW", (v) => { building.width = Math.max(10, Number(v) || 120); refreshAnchors(building); });
    bind("pH", (v) => { building.height = Math.max(10, Number(v) || 80); refreshAnchors(building); });
    bindJson("pA", (v) => { building.anchorNodeIds = Array.isArray(v) ? v : []; refreshAnchors(building); });
  }

  function cameraProps(camera) {
    const calibrations = [["", "未关联"], ...state.model.cameraCalibrations.map((item) => [item.id, `${item.id} ${item.name}`])];
    const streams = [["", "自定义"], ...M.CAMERA_PRESETS.map((item) => [item.id, `${item.id} · ${item.place}`])];
    el.properties.innerHTML = `${field("ID", "pId", camera.id, true)}${field("名称", "pName", camera.name)}${selectField("沙盘视频流", "pStreamPreset", camera.streamPresetId, streams)}${field("所属地点", "pPlace", camera.place)}${selectField("画面标定", "pCalibration", camera.calibrationId, calibrations)}${field("RTSP 地址", "pRtsp", camera.rtspUrl)}${num("X", "pX", camera.x)}${num("Y", "pY", camera.y)}${num("方向", "pDir", camera.direction)}${num("视场角", "pFov", camera.fov)}${num("范围", "pRange", camera.range)}<label>路面高度<input id="pHeight" type="number" step="0.1" value="${esc(camera.height ?? 500)}"></label>${area("覆盖格点", "pCells", camera.coverage.gridCells)}`;
    bind("pName", (v) => { camera.name = v; });
    bind("pStreamPreset", (v) => {
      camera.streamPresetId = v;
      const preset = M.CAMERA_PRESETS.find((item) => item.id === v);
      if (preset) { camera.place = preset.place; camera.rtspUrl = preset.url; }
    });
    bind("pPlace", (v) => { camera.place = v; });
    bind("pCalibration", (v) => { camera.calibrationId = v; camera.pointBindings = []; state.selectedImagePointId = ""; });
    bind("pRtsp", (v) => {
      camera.rtspUrl = v.trim();
      const preset = M.CAMERA_PRESETS.find((item) => item.url === camera.rtspUrl);
      camera.streamPresetId = preset?.id || "";
    });
    bind("pX", (v) => { camera.x = Number(v) || 0; });
    bind("pY", (v) => { camera.y = Number(v) || 0; });
    bind("pDir", (v) => { camera.direction = Number(v) || 0; });
    bind("pFov", (v) => { camera.fov = Number(v) || 60; });
    bind("pRange", (v) => { camera.range = Number(v) || 240; });
    bind("pHeight", (v) => { camera.height = Number(v) || 0; });
    bindJson("pCells", (v) => { camera.coverage.gridCells = Array.isArray(v) ? v : []; });
  }

  function renderCameraImagePanel() {
    if (!state.selected || state.selected.type !== "camera") {
      el.cameraImagePanel.innerHTML = '<div class="empty">选中摄像头后上传画面并点击标定点</div>';
      return;
    }
    const camera = entity("camera", state.selected.id);
    if (!camera) return;
    const calibration = activeCalibration(camera);
    const hasCalibrationImage = Boolean(calibrationImageSource(calibration));
    el.cameraImagePanel.innerHTML = `
      <div class="mini-row">
        <button id="newCalibration" type="button">新建标定</button>
        <button id="captureRtspFrame" type="button" ${camera.rtspUrl ? "" : "disabled"}>截取 RTSP 帧</button>
      </div>
      <label>标定名称<input id="calibrationName" value="${esc(calibration?.name || "")}" ${calibration ? "" : "disabled"}></label>
      <label>导入画面<input id="cameraImageInput" type="file" accept="image/*" ${calibration ? "" : "disabled"}></label>
      <canvas id="cameraImageCanvas" width="480" height="270" aria-label="摄像头画面标定"></canvas>
      <div class="mini-row">
        <button id="zoomCalibration" type="button" ${hasCalibrationImage ? "" : "disabled"}>放大标定</button>
        <button id="connectImagePoints" type="button" ${hasCalibrationImage ? "" : "disabled"}>连接画面两点</button>
      </div>
      <button id="deleteImagePoint" class="danger" type="button">删除选中画面点</button>
      <p class="hint">点击画面生成点，切换"标点"模式后在网格上放置对应标点。</p>
      <div id="cameraPointList" class="camera-point-list"></div>
      <div id="correspondenceProps" class="correspondence-props"></div>
    `;
    bindCameraImagePanel(camera, calibration);
    drawCameraImage(camera, calibration);
    renderCameraPointList(camera, calibration);
    renderCorrespondenceProps(camera, calibration);
  }

  function activeCalibration(camera) {
    return state.model.cameraCalibrations.find((item) => item.id === camera.calibrationId) || null;
  }

  function calibrationImageSource(calibration) {
    const image = calibration?.image;
    if (!image) return "";
    if (image.dataUrl) return image.dataUrl;
    return image.src ? new URL(image.src, document.baseURI).href : "";
  }

  function bindCameraImagePanel(camera, calibration) {
    const fileInput = document.getElementById("cameraImageInput");
    const canvas = document.getElementById("cameraImageCanvas");
    document.getElementById("newCalibration").addEventListener("click", () => createCalibration(camera));
    document.getElementById("captureRtspFrame").addEventListener("click", () => captureRtspFrame(camera));
    const nameInput = document.getElementById("calibrationName");
    if (calibration) nameInput.addEventListener("change", () => { remember(); calibration.name = nameInput.value || calibration.id; sync(); });
    fileInput.addEventListener("change", () => {
      const file = fileInput.files?.[0];
      if (!file || !calibration) return;
      const reader = new FileReader();
      reader.onload = () => {
        const image = new Image();
        image.onload = () => {
          remember();
          calibration.image = { name: file.name, dataUrl: String(reader.result), width: image.naturalWidth, height: image.naturalHeight, capturedAt: new Date().toISOString() };
          sync();
        };
        image.src = String(reader.result);
      };
      reader.readAsDataURL(file);
    });
    document.getElementById("deleteImagePoint").addEventListener("click", () => deleteCameraImagePoint(camera, calibration));
    const zoomBtn = document.getElementById("zoomCalibration");
    if (zoomBtn) zoomBtn.addEventListener("click", () => openZoomCalibration(camera, calibration));
    const connectBtn = document.getElementById("connectImagePoints");
    if (connectBtn) connectBtn.addEventListener("click", () => {
      openZoomCalibration(camera, calibration);
      state.zoomLineConnectActive = true;
      updateZoomStatus("连接模式：点击起点，再点击终点");
    });
    canvas.addEventListener("click", (event) => addCameraImagePoint(camera, calibration, event));
  }

  function createCalibration(camera) {
    remember();
    const calibration = { id: M.nextId("calibration", state.model.cameraCalibrations), name: `画面标定 ${state.model.cameraCalibrations.length + 1}`, image: null, points: [], lines: [] };
    state.model.cameraCalibrations.push(calibration);
    camera.calibrationId = calibration.id;
    camera.pointBindings = [];
    state.selectedImagePointId = "";
    sync();
  }

  async function captureRtspFrame(camera) {
    let calibration = activeCalibration(camera);
    if (!calibration) {
      createCalibration(camera);
      calibration = activeCalibration(camera);
    }
    const button = document.getElementById("captureRtspFrame");
    button.disabled = true;
    button.textContent = "正在截帧...";
    status("正在连接 RTSP 摄像头");
    try {
      const response = await fetch("http://127.0.0.1:8765/api/rtsp/frame", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: camera.rtspUrl })
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error?.message || "截帧失败");
      const dimensions = await imageDimensions(payload.data.dataUrl);
      remember();
      calibration.image = { ...payload.data, ...dimensions };
      sync();
      status("RTSP 画面已截取");
    } catch (err) {
      status(`RTSP 截帧失败：${err.message}。请运行 start_server.ps1`);
      button.disabled = false;
      button.textContent = "截取 RTSP 帧";
    }
  }

  function imageDimensions(dataUrl) {
    return new Promise((resolve, reject) => {
      const image = new Image();
      image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
      image.onerror = () => reject(new Error("截取的画面无法解码"));
      image.src = dataUrl;
    });
  }

  function addCameraImagePoint(camera, calibration, event) {
    const source = calibrationImageSource(calibration);
    if (!source) {
      status("请先导入画面或截取 RTSP 帧");
      return;
    }
    const canvas = event.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const scale = imageCanvasScale(calibration, canvas);
    const x = (event.clientX - rect.left - scale.x) / scale.scale;
    const y = (event.clientY - rect.top - scale.y) / scale.scale;
    if (x < 0 || y < 0 || x > scale.imageWidth || y > scale.imageHeight) return;
    const existing = (calibration.points || []).find((point) => Math.hypot(x - point.x, y - point.y) <= 12 / scale.scale);
    if (existing) {
      state.selectedImagePointId = existing.id;
      state.selectedImageLineId = "";
      drawCameraImage(camera, calibration);
      renderCameraPointList(camera, calibration);
      renderCorrespondenceProps(camera, calibration);
      status(`已选择 ${existing.id}`);
      return;
    }
    remember();
    calibration.points = calibration.points || [];
    const point = {
      id: M.nextId("imgpt", calibration.points),
      name: `画面点 ${calibration.points.length + 1}`,
      x: Math.round(x),
      y: Math.round(y)
    };
    calibration.points.push(point);
    state.selectedImagePointId = point.id;
    sync();
  }

  function deleteCameraImagePoint(camera, calibration) {
    if (!state.selectedImagePointId || !calibration) return;
    remember();
    removeCalibrationPoint(camera, calibration, state.selectedImagePointId);
    state.selectedImagePointId = "";
    sync();
  }

  function removeCalibrationPoint(camera, calibration, pointId) {
    calibration.points = (calibration.points || []).filter((point) => point.id !== pointId);
    calibration.lines = (calibration.lines || []).filter((line) => line.fromPointId !== pointId && line.toPointId !== pointId);
    camera.pointBindings = (camera.pointBindings || []).filter((binding) => binding.imagePointId !== pointId);
    if (state.selectedImageLineId && !(calibration.lines || []).some((line) => line.id === state.selectedImageLineId)) state.selectedImageLineId = "";
    if (state.zoomLineStartId === pointId) state.zoomLineStartId = "";
    if (!state.zoomLineStartId) state.zoomLineConnectActive = false;
  }

  function drawCameraImage(camera, calibration) {
    const canvas = document.getElementById("cameraImageCanvas");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#101820";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const source = calibrationImageSource(calibration);
    if (!source) {
      ctx.fillStyle = "#9aa8b3";
      ctx.font = "13px Segoe UI, Microsoft YaHei, Arial";
      ctx.textAlign = "center";
      ctx.fillText("上传摄像头画面后点击确定点", canvas.width / 2, canvas.height / 2);
      return;
    }
    const image = new Image();
    image.onload = () => {
      const scale = imageCanvasScale(calibration, canvas);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#101820";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, scale.x, scale.y, scale.imageWidth * scale.scale, scale.imageHeight * scale.scale);
      drawImageLinesAndPoints(ctx, calibration, scale);
    };
    image.src = source;
  }

  function imageCanvasScale(calibration, canvas) {
    const imageWidth = calibration?.image?.width || canvas.width;
    const imageHeight = calibration?.image?.height || canvas.height;
    const scale = Math.min(canvas.width / imageWidth, canvas.height / imageHeight);
    return { scale, imageWidth, imageHeight, x: (canvas.width - imageWidth * scale) / 2, y: (canvas.height - imageHeight * scale) / 2 };
  }

  function drawImageLinesAndPoints(ctx, calibration, scale) {
    const points = calibration.points || [];
    const byId = new Map(points.map((point) => [point.id, point]));
    ctx.save();
    (calibration.lines || []).forEach((line) => {
      const a = byId.get(line.fromPointId);
      const b = byId.get(line.toPointId);
      if (!a || !b) return;
      const selected = state.selectedImageLineId === line.id;
      ctx.strokeStyle = selected ? "#f59e0b" : "rgba(34,211,238,0.88)";
      ctx.lineWidth = selected ? 4 : 2;
      ctx.beginPath();
      ctx.moveTo(scale.x + a.x * scale.scale, scale.y + a.y * scale.scale);
      ctx.lineTo(scale.x + b.x * scale.scale, scale.y + b.y * scale.scale);
      ctx.stroke();
    });
    points.forEach((point, index) => {
      const x = scale.x + point.x * scale.scale;
      const y = scale.y + point.y * scale.scale;
      const selected = state.selectedImagePointId === point.id;
      ctx.fillStyle = selected ? "#22d3ee" : "#f59e0b";
      ctx.strokeStyle = "#111820";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(x, y, selected ? 6 : 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "11px Segoe UI, Microsoft YaHei, Arial";
      ctx.fillText(String(index + 1), x + 8, y - 8);
    });
    if (state.zoomLineStartId && byId.has(state.zoomLineStartId)) {
      const point = byId.get(state.zoomLineStartId);
      const x = scale.x + point.x * scale.scale;
      const y = scale.y + point.y * scale.scale;
      ctx.strokeStyle = "#22d3ee";
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(x, y, 10, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();
  }

  function zoomCanvasScale(calibration, canvas) {
    const imageWidth = calibration?.image?.width || canvas.width;
    const imageHeight = calibration?.image?.height || canvas.height;
    const scale = Math.min(canvas.width / imageWidth, canvas.height / imageHeight);
    return { scale, imageWidth, imageHeight, x: (canvas.width - imageWidth * scale) / 2, y: (canvas.height - imageHeight * scale) / 2 };
  }

  function openZoomCalibration(camera, calibration) {
    if (!calibrationImageSource(calibration)) {
      status("请先导入画面或截取 RTSP 帧");
      return;
    }
    closeZoomCalibration();
    state.zoomLineStartId = "";
    state.zoomLineConnectActive = false;
    state.selectedImageLineId = "";
    const overlay = document.createElement("div");
    overlay.className = "zoom-overlay";
    overlay.id = "zoomOverlay";
    overlay.innerHTML = `
      <div class="zoom-toolbar">
        <span id="zoomStatus" class="zoom-status">点击画面添加或选择点</span>
        <button id="zoomConnectLine" type="button">连接两点</button>
        <button id="zoomDeletePoint" class="danger" type="button">删除点</button>
        <button id="zoomDeleteLine" class="danger" type="button">删除线</button>
        <button id="zoomClearLines" class="danger" type="button">清空连线</button>
        <button id="zoomCloseBtn" type="button">返回</button>
      </div>
      <canvas id="zoomCanvas"></canvas>
    `;
    document.body.appendChild(overlay);

    const canvas = document.getElementById("zoomCanvas");

    function resizeZoom() {
      const toolbar = overlay.querySelector(".zoom-toolbar");
      const toolbarH = toolbar ? toolbar.offsetHeight : 0;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight - toolbarH;
      drawZoomCanvas(camera, calibration, canvas);
    }

    resizeZoom();
    const resizeHandler = () => resizeZoom();
    window.addEventListener("resize", resizeHandler);
    state.zoomCleanup = () => window.removeEventListener("resize", resizeHandler);

    document.getElementById("zoomCloseBtn").addEventListener("click", () => {
      closeZoomCalibration();
      drawCameraImage(camera, calibration);
      renderCameraPointList(camera, calibration);
    });

    document.getElementById("zoomConnectLine").addEventListener("click", () => {
      state.zoomLineStartId = "";
      state.zoomLineConnectActive = true;
      state.selectedImageLineId = "";
      updateZoomStatus("连接模式：点击起点，再点击终点");
      drawZoomCanvas(camera, calibration, canvas);
    });
    document.getElementById("zoomDeletePoint").addEventListener("click", () => deleteZoomPoint(camera, calibration, canvas));
    document.getElementById("zoomDeleteLine").addEventListener("click", () => deleteZoomLine(calibration, camera, canvas));
    document.getElementById("zoomClearLines").addEventListener("click", () => clearZoomLines(calibration, camera, canvas));
    canvas.addEventListener("click", (event) => handleZoomCanvasClick(camera, calibration, event, canvas));
  }

  function closeZoomCalibration() {
    if (state.zoomCleanup) state.zoomCleanup();
    state.zoomCleanup = null;
    const overlay = document.getElementById("zoomOverlay");
    if (overlay) overlay.remove();
    state.zoomLineStartId = "";
    state.zoomLineConnectActive = false;
  }

  function drawZoomCanvas(camera, calibration, canvas) {
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#0a0f14";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const source = calibrationImageSource(calibration);
    if (!source) return;
    const image = new Image();
    image.onload = () => {
      const scale = zoomCanvasScale(calibration, canvas);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.fillStyle = "#0a0f14";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(image, scale.x, scale.y, scale.imageWidth * scale.scale, scale.imageHeight * scale.scale);
      drawImageLinesAndPoints(ctx, calibration, scale);
    };
    image.src = source;
  }

  function handleZoomCanvasClick(camera, calibration, event, canvas) {
    if (!calibrationImageSource(calibration)) return;
    const rect = canvas.getBoundingClientRect();
    const scale = zoomCanvasScale(calibration, canvas);
    const clickX = event.clientX - rect.left;
    const clickY = event.clientY - rect.top;
    if (clickX < scale.x || clickX > scale.x + scale.imageWidth * scale.scale || clickY < scale.y || clickY > scale.y + scale.imageHeight * scale.scale) return;
    const pointId = findZoomPointHit(calibration, scale, clickX, clickY);
    if (state.zoomLineConnectActive) {
      if (!pointId) {
        updateZoomStatus(state.zoomLineStartId ? "请点击一个已有画面点作为线段终点" : "请点击一个已有画面点作为线段起点");
        return;
      }
      if (!state.zoomLineStartId) {
        state.zoomLineStartId = pointId;
        state.selectedImagePointId = pointId;
        updateZoomStatus(`已选择起点 ${pointId}，请点击终点`);
        drawZoomCanvas(camera, calibration, canvas);
        return;
      }
      if (pointId === state.zoomLineStartId) {
        updateZoomStatus("起点和终点不能相同");
        return;
      }
      remember();
      const created = M.toggleCalibrationLine(calibration, state.zoomLineStartId, pointId);
      state.zoomLineStartId = "";
      state.zoomLineConnectActive = false;
      state.selectedImagePointId = pointId;
      state.selectedImageLineId = "";
      sync(false);
      updateZoomStatus(created ? "线段已创建" : "线段已取消");
      drawZoomCanvas(camera, calibration, canvas);
      return;
    }
    if (pointId) {
      state.selectedImagePointId = pointId;
      state.selectedImageLineId = "";
      updateZoomStatus(`已选择 ${pointId}`);
      drawZoomCanvas(camera, calibration, canvas);
      return;
    }
    const lineId = findZoomLineHit(calibration, scale, clickX, clickY);
    if (lineId) {
      state.selectedImageLineId = lineId;
      state.selectedImagePointId = "";
      updateZoomStatus(`已选择线段 ${lineId}`);
      drawZoomCanvas(camera, calibration, canvas);
      return;
    }
    remember();
    calibration.points = calibration.points || [];
    const point = {
      id: M.nextId("imgpt", calibration.points),
      name: `画面点 ${calibration.points.length + 1}`,
      x: Math.round((clickX - scale.x) / scale.scale),
      y: Math.round((clickY - scale.y) / scale.scale)
    };
    calibration.points.push(point);
    state.selectedImagePointId = point.id;
    state.selectedImageLineId = "";
    sync(false);
    updateZoomStatus(`已新增 ${point.id}`);
    drawZoomCanvas(camera, calibration, canvas);
  }

  function findZoomPointHit(calibration, scale, x, y) {
    return (calibration.points || []).find((point) => Math.hypot(x - (scale.x + point.x * scale.scale), y - (scale.y + point.y * scale.scale)) <= 12)?.id || "";
  }

  function findZoomLineHit(calibration, scale, x, y) {
    const byId = new Map((calibration.points || []).map((point) => [point.id, point]));
    for (let i = (calibration.lines || []).length - 1; i >= 0; i -= 1) {
      const line = calibration.lines[i];
      const a = byId.get(line.fromPointId);
      const b = byId.get(line.toPointId);
      if (a && b && G.distanceToSegment({ x, y }, { x: scale.x + a.x * scale.scale, y: scale.y + a.y * scale.scale }, { x: scale.x + b.x * scale.scale, y: scale.y + b.y * scale.scale }) <= 8) return line.id;
    }
    return "";
  }

  function deleteZoomPoint(camera, calibration, canvas) {
    if (!state.selectedImagePointId) { updateZoomStatus("请先选择要删除的画面点"); return; }
    remember();
    removeCalibrationPoint(camera, calibration, state.selectedImagePointId);
    state.selectedImagePointId = "";
    sync(false);
    updateZoomStatus("画面点及其关联线段已删除");
    drawZoomCanvas(camera, calibration, canvas);
  }

  function deleteZoomLine(calibration, camera, canvas) {
    if (!state.selectedImageLineId) { updateZoomStatus("请先点击要删除的线段"); return; }
    remember();
    calibration.lines = (calibration.lines || []).filter((line) => line.id !== state.selectedImageLineId);
    state.selectedImageLineId = "";
    sync(false);
    updateZoomStatus("线段已删除");
    drawZoomCanvas(camera, calibration, canvas);
  }

  function clearZoomLines(calibration, camera, canvas) {
    if (!(calibration.lines || []).length) return;
    remember();
    calibration.lines = [];
    state.selectedImageLineId = "";
    state.zoomLineStartId = "";
    state.zoomLineConnectActive = false;
    sync(false);
    updateZoomStatus("所有连线已清除，画面点保留");
    drawZoomCanvas(camera, calibration, canvas);
  }

  function updateZoomStatus(text) {
    const statusEl = document.getElementById("zoomStatus");
    if (statusEl) statusEl.textContent = text;
  }

  function renderCameraPointList(camera, calibration) {
    const list = document.getElementById("cameraPointList");
    if (!list) return;
    const points = calibration?.points || [];
    const bindings = new Map((camera.pointBindings || []).map((binding) => [binding.imagePointId, binding]));
    list.innerHTML = points.length ? points.map((point, index) => `
      <button type="button" class="${state.selectedImagePointId === point.id ? "selected" : ""}" data-id="${point.id}">
        ${index + 1}. ${esc(point.name)} · ${esc(point.id)} (${point.x}, ${point.y}) → ${esc(bindingLabel(bindings.get(point.id)))}
      </button>
    `).join("") : '<div class="empty">尚未添加画面点</div>';
    list.querySelectorAll("button").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedImagePointId = button.dataset.id;
        drawCameraImage(camera, calibration);
        renderCameraPointList(camera, calibration);
        renderCorrespondenceProps(camera, calibration);
      });
    });
  }

  function renderCorrespondenceProps(camera, calibration) {
    const container = document.getElementById("correspondenceProps");
    if (!container) return;
    if (!state.selectedImagePointId) {
      container.innerHTML = '<div class="empty">选中画面点后显示标点属性</div>';
      return;
    }
    const binding = (camera.pointBindings || []).find((b) => b.imagePointId === state.selectedImagePointId);
    if (!binding?.worldPoint) {
      container.innerHTML = '<div class="empty">该画面点尚未放置标点（切换"标点"模式后在网格上点击）</div>';
      return;
    }
    const wp = binding.worldPoint;
    container.innerHTML = `
      <label>标点 X<input id="cpX" type="number" step="1" value="${esc(wp.x)}"></label>
      <label>标点 Y<input id="cpY" type="number" step="1" value="${esc(wp.y)}"></label>
      <label>标点高度<input id="cpHeight" type="number" step="0.1" value="${esc(wp.height ?? 500)}"></label>
      <button id="deleteCorrespondence" class="danger" type="button">删除标点</button>
    `;
    const cam = camera;
    bind("cpX", (v) => { binding.worldPoint.x = Number(v) || 0; });
    bind("cpY", (v) => { binding.worldPoint.y = Number(v) || 0; });
    bind("cpHeight", (v) => { binding.worldPoint.height = Number(v) || 0; });
    document.getElementById("deleteCorrespondence").addEventListener("click", () => {
      remember();
      deleteCorrespondencePoint(cam, state.selectedImagePointId);
      sync();
    });
  }

  function bindingLabel(binding) {
    if (!binding) return "未绑定";
    if (binding.gridCellId) return binding.gridCellId;
    if (binding.nodeId) return `端点 ${binding.nodeId}`;
    if (binding.laneId) return `车道 ${binding.laneId}`;
    if (binding.buildingId) return `建筑物 ${binding.buildingId}`;
    if (binding.worldPoint) return `标点 ${binding.worldPoint.x},${binding.worldPoint.y}·H${binding.worldPoint.height ?? 500}`;
    return "未绑定";
  }

  function groupProps(group) {
    el.properties.innerHTML = `${field("ID", "pId", group.id, true)}${field("名称", "pName", group.name)}${area("道路内节点 ID", "pNodes", group.nodeIds)}${field("排序", "pOrder", group.order)}`;
    bind("pName", (v) => { group.name = v; });
    bindJson("pNodes", (v) => { group.nodeIds = Array.isArray(v) ? v : []; M.syncGroupMembership(state.model); });
    bind("pOrder", (v) => { group.order = v || "auto"; });
  }

  function setNodeGroup(node, groupId) {
    state.model.laneEndpointGroups.forEach((group) => { group.nodeIds = group.nodeIds.filter((id) => id !== node.id); });
    node.groupId = groupId;
    const group = state.model.laneEndpointGroups.find((item) => item.id === groupId);
    if (group && !group.nodeIds.includes(node.id)) group.nodeIds.push(node.id);
  }

  function renderList() {
    const rows = [
      ...state.model.nodes.map((item) => ({ type: "node", item, meta: `${item.type} (${item.x},${item.y})` })),
      ...state.model.lanes.map((item) => ({ type: "lane", item, meta: `${item.endpoint1} → ${item.endpoint2}` })),
      ...state.model.laneEndpointGroups.map((item) => ({ type: "group", item, meta: `${item.nodeIds.length} 个节点` })),
      ...state.model.buildings.map((item) => ({ type: "building", item, meta: `${item.width} × ${item.height}` })),
      ...state.model.cameras.map((item) => ({ type: "camera", item, meta: `${item.place || "未设地点"} · ${item.coverage.gridCells.length} 格 · H${item.height ?? 500}` }))
    ];
    el.entityList.innerHTML = rows.map(({ type, item, meta }) => `<button type="button" class="${state.selected?.type === type && state.selected?.id === item.id ? "selected" : ""}" data-type="${type}" data-id="${item.id}"><span class="entity-title">${esc(item.name || item.id)}</span><span class="entity-meta">${type} · ${esc(meta)}</span></button>`).join("");
    el.entityList.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => { select(btn.dataset.type, btn.dataset.id); sync(); }));
  }

  function sync(updateJsonFlag = false) {
    M.normalize(state.model);
    el.nodeType.value = state.nodeType;
    el.gridSize.value = state.model.world.gridSize;
    el.nodeCount.textContent = state.model.nodes.length;
    el.laneCount.textContent = state.model.lanes.length;
    el.groupCount.textContent = state.model.laneEndpointGroups.length;
    el.buildingCount.textContent = state.model.buildings.length;
    el.cameraCount.textContent = state.model.cameras.length;
    renderProperties();
    renderCameraImagePanel();
    renderList();
    if (updateJsonFlag) updateJson();
    draw();
  }

  function updateJson() {
    el.jsonOutput.value = JSON.stringify(M.exportPayload(state.model), null, 2);
  }

  function importJson() {
    try {
      const payload = JSON.parse(el.jsonOutput.value);
      importJsonPayload(payload, "JSON 已导入");
    } catch (err) {
      status(`JSON 导入失败：${err.message}`);
    }
  }

  function importJsonFile() {
    const file = el.importJsonFile.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const payload = JSON.parse(String(reader.result || ""));
        importJsonPayload(payload, `已导入 ${file.name}`);
      } catch (err) {
        status(`JSON 文件导入失败：${err.message}`);
      } finally {
        el.importJsonFile.value = "";
      }
    };
    reader.onerror = () => {
      status("JSON 文件读取失败");
      el.importJsonFile.value = "";
    };
    reader.readAsText(file, "utf-8");
  }

  function importJsonPayload(payload, message) {
    remember();
    state.model = M.normalize(payload.model || payload);
    state.selected = null;
    state.selectedImagePointId = "";
    fitView();
    sync(false);
    updateJson();
    status(message);
  }

  function downloadJson() {
    updateJson();
    const blob = new Blob([el.jsonOutput.value], { type: "application/json;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${state.model.name}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function remember() {
    history.push(M.lightweightClone(state.model));
    if (history.length > 60) history.shift();
  }

  function undo() {
    if (!history.length) return;
    const runtimeImages = new Map(state.model.cameraCalibrations.map((item) => [item.id, item.image?.dataUrl]).filter(([, dataUrl]) => dataUrl));
    state.model = history.pop();
    state.model.cameraCalibrations.forEach((item) => {
      if (item.image && runtimeImages.has(item.id)) item.image.dataUrl = runtimeImages.get(item.id);
    });
    state.selected = null;
    sync();
    status("已撤销");
  }

  function entity(type, id) {
    return collection(type).find((item) => item.id === id);
  }

  function collection(type) {
    return { node: state.model.nodes, lane: state.model.lanes, building: state.model.buildings, camera: state.model.cameras, group: state.model.laneEndpointGroups }[type] || [];
  }

  function select(type, id) {
    state.selected = { type, id };
  }

  function toggle(key, button) {
    state[key] = !state[key];
    button.classList.toggle("active", state[key]);
    sync(false);
  }

  function resize() {
    const rect = el.canvas.getBoundingClientRect();
    el.canvas.width = Math.max(420, Math.floor(rect.width));
    el.canvas.height = Math.max(320, Math.floor(rect.height));
    draw();
  }

  function fitView() {
    const margin = 70;
    const zx = (el.canvas.width - margin * 2) / state.model.world.width;
    const zy = (el.canvas.height - margin * 2) / state.model.world.height;
    state.view.zoom = G.clamp(Math.min(zx, zy), 0.25, 2);
    state.view.x = (el.canvas.width - state.model.world.width * state.view.zoom) / 2;
    state.view.y = (el.canvas.height - state.model.world.height * state.view.zoom) / 2;
    draw();
  }

  function draw() {
    if (el.canvas) R.render(el.canvas.getContext("2d"), state);
  }

  function pointer(e) {
    const rect = el.canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  function snapped(point) {
    return state.snap ? G.snapPoint(point, state.model.world.gridSize) : point;
  }

  function clampWorld(point) {
    return {
      x: G.clamp(point.x, 0, state.model.world.width),
      y: G.clamp(point.y, 0, state.model.world.height)
    };
  }

  function field(label, id, value, disabled) {
    return `<label>${label}<input id="${id}" value="${esc(value ?? "")}" ${disabled ? "disabled" : ""}></label>`;
  }
  function num(label, id, value) {
    return `<label>${label}<input id="${id}" type="number" step="1" value="${esc(value ?? 0)}"></label>`;
  }
  function selectField(label, id, value, opts) {
    return `<label>${label}<select id="${id}">${opts.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(value) ? "selected" : ""}>${esc(t)}</option>`).join("")}</select></label>`;
  }
  function area(label, id, value) {
    return `<label>${label}<textarea id="${id}" spellcheck="false">${esc(JSON.stringify(value, null, 2))}</textarea></label>`;
  }
  function bind(id, cb) {
    const input = document.getElementById(id);
    if (!input) return;
    input.addEventListener("change", () => { remember(); cb(input.value); sync(); });
  }
  function bindJson(id, cb) {
    bind(id, (value) => {
      try { cb(JSON.parse(value || "null")); } catch (_) { status("JSON 字段解析失败"); }
    });
  }
  function esc(value) {
    return String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
  }
  function status(text) {
    el.status.textContent = text;
  }

  window.addEventListener("DOMContentLoaded", init);
})();
