import { analyzeFlowMatching, applyDeterministicMatches, buildConfirmedExport, rebuildDirections, suggestSpatialMatches, toggleLaneMatch } from "./flow_matcher_model.js";

const TEMPLATE_URL = "./analysis/node-flow-template.v1.json";
const ROAD_URL = "./analysis/baseline/road_logic_model (4).road-lane.v1.json";
const CONFIRMED_URL = "./confirmed-node-flow.v1.json";
const STORAGE_KEY = "road_logic_modeler.confirmed-node-flow.v1";

const state = {
  template: null,
  road: null,
  filter: "review",
  selectedNodeId: null,
  selectedAssignmentId: null,
  pendingIncomingLaneId: null,
  reversedLaneIds: new Set(),
  editorTab: "matching",
  solverReport: null,
};

const elements = Object.fromEntries([
  "loadStatus", "nodeCount", "nodeList", "worldCanvas", "nodeCanvas", "nodeSubtitle",
  "classificationBadge", "assignmentSelect", "assignmentMeta", "incomingLanes", "outgoingLanes",
  "matchLines", "matchList", "matcherStage", "saveStatus", "clearAssignmentButton",
  "suggestAssignmentButton", "importButton", "importInput", "exportButton",
  "matchingTab", "directionTab", "matchingView", "directionView", "directionList",
  "applyButton", "solverReport",
].map((id) => [id, document.getElementById(id)]));

function currentNode() {
  return state.template?.nodes.find((item) => item.nodeId === state.selectedNodeId) ?? null;
}

function currentAssignment() {
  return currentNode()?.roadBundleAssignments.find((item) => item.id === state.selectedAssignmentId) ?? null;
}

function classificationLabel(value) {
  return {
    simple_continuation: "直通",
    simple_corner: "转角",
    simple_branch: "汇流 / 分流",
    chaotic_intersection: "混沌路口",
    three_way_complex: "复杂三向",
    terminal: "边界终点",
    isolated: "孤立节点",
  }[value] ?? value;
}

function filteredNodes() {
  if (!state.template) return [];
  if (state.filter === "review") return state.template.nodes.filter((item) => item.assignmentPolicy === "manual_road_bundle_mapping");
  if (state.filter === "chaotic") return state.template.nodes.filter((item) => item.assignmentPolicy === "road_port_only" && item.armCount >= 3);
  return state.template.nodes;
}

function findLane(laneId) {
  return state.road.lanes.find((item) => item.id === laneId);
}

function restoreConfirmed(payload) {
  for (const node of state.template.nodes) {
    for (const assignment of node.roadBundleAssignments ?? []) assignment.laneAssignments = [];
  }
  state.reversedLaneIds = new Set((payload?.laneDirectionOverrides ?? []).map((item) => item.laneId));
  rebuildDirections(state.template, state.road, state.reversedLaneIds);
  for (const savedNode of payload?.nodes ?? []) {
    const node = state.template.nodes.find((item) => item.nodeId === savedNode.nodeId);
    if (!node) continue;
    for (const savedAssignment of savedNode.roadBundleAssignments ?? []) {
      const assignment = node.roadBundleAssignments.find((item) => item.id === savedAssignment.id);
      if (assignment) assignment.laneAssignments = (savedAssignment.laneAssignments ?? []).map((item) => ({ ...item }));
    }
  }
}

function saveLocal() {
  if (state.solverReport) state.solverReport = analyzeFlowMatching(state.template);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(buildConfirmedExport(state.template, state.road, state.reversedLaneIds)));
  elements.saveStatus.textContent = "已自动保存";
  window.setTimeout(() => { elements.saveStatus.textContent = "自动保存"; }, 900);
}

function setSelectedNode(nodeId) {
  state.selectedNodeId = nodeId;
  const node = currentNode();
  state.selectedAssignmentId = node?.roadBundleAssignments[0]?.id ?? null;
  state.pendingIncomingLaneId = null;
  render();
}

function resizeCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  const width = Math.max(1, Math.round(rect.width * ratio));
  const height = Math.max(1, Math.round(rect.height * ratio));
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return { context, width: rect.width, height: rect.height };
}

function renderWorldCanvas() {
  const { context, width, height } = resizeCanvas(elements.worldCanvas);
  context.clearRect(0, 0, width, height);
  if (!state.road) return;
  const world = state.road.world;
  const pad = 10;
  const scale = Math.min((width - pad * 2) / world.width, (height - pad * 2) / world.height);
  const offsetX = (width - world.width * scale) / 2;
  const offsetY = (height - world.height * scale) / 2;
  const nodes = new Map(state.road.nodes.map((item) => [item.id, item]));
  const screen = (point) => ({ x: offsetX + point.x * scale, y: offsetY + point.y * scale });
  context.lineWidth = 1;
  context.strokeStyle = "#38505d";
  for (const bundle of state.road.roadBundles) {
    const a = screen(nodes.get(bundle.endpointIds[0]).position);
    const b = screen(nodes.get(bundle.endpointIds[1]).position);
    context.beginPath(); context.moveTo(a.x, a.y); context.lineTo(b.x, b.y); context.stroke();
  }
  for (const node of state.template.nodes) {
    const point = screen(node.position);
    const selected = node.nodeId === state.selectedNodeId;
    context.beginPath();
    context.arc(point.x, point.y, selected ? 4.5 : 2.7, 0, Math.PI * 2);
    context.fillStyle = selected ? "#ffffff" : node.assignmentPolicy === "manual_road_bundle_mapping" ? "#51c98b" : node.armCount >= 3 ? "#e46c76" : "#71838e";
    context.fill();
  }
}

function lanePortLayout(node, center, radius) {
  const ports = new Map();
  for (const arm of node.arms) {
    const angle = arm.angleDegrees * Math.PI / 180;
    const direction = { x: Math.cos(angle), y: Math.sin(angle) };
    const normal = { x: -direction.y, y: direction.x };
    const laneIds = arm.laneIds;
    laneIds.forEach((laneId, index) => {
      const offset = (index - (laneIds.length - 1) / 2) * 13;
      ports.set(laneId, { x: center.x + direction.x * radius + normal.x * offset, y: center.y + direction.y * radius + normal.y * offset });
    });
  }
  return ports;
}

function drawBezier(context, a, b, center, color, width = 3) {
  context.beginPath();
  context.moveTo(a.x, a.y);
  context.bezierCurveTo((a.x + center.x) / 2, (a.y + center.y) / 2, (b.x + center.x) / 2, (b.y + center.y) / 2, b.x, b.y);
  context.strokeStyle = color;
  context.lineWidth = width;
  context.stroke();
}

function renderNodeCanvas() {
  const { context, width, height } = resizeCanvas(elements.nodeCanvas);
  context.clearRect(0, 0, width, height);
  const node = currentNode();
  if (!node) return;
  const center = { x: width / 2, y: height / 2 };
  const radius = Math.max(120, Math.min(width, height) * 0.32);
  const coreRadius = Math.max(54, Math.min(88, 34 + node.armCount * 12));
  context.lineCap = "butt";
  for (const arm of node.arms) {
    const angle = arm.angleDegrees * Math.PI / 180;
    const end = { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius };
    const roadWidth = Math.max(40, arm.laneIds.length * 14 + 16);
    context.beginPath(); context.moveTo(center.x, center.y); context.lineTo(end.x, end.y);
    context.strokeStyle = "#344b55"; context.lineWidth = roadWidth; context.stroke();
    context.fillStyle = "#a6b5bd";
    context.font = "11px Segoe UI";
    context.textAlign = Math.cos(angle) >= 0 ? "left" : "right";
    context.fillText(`${arm.otherNodeId} · ${arm.laneIds.length} 车道`, end.x + (Math.cos(angle) >= 0 ? 8 : -8), end.y - 6);
    const crossRadius = coreRadius + 30;
    const normal = { x: -Math.sin(angle), y: Math.cos(angle) };
    for (let stripe = -2; stripe <= 2; stripe++) {
      const along = crossRadius + stripe * 5;
      const x = center.x + Math.cos(angle) * along;
      const y = center.y + Math.sin(angle) * along;
      context.beginPath();
      context.moveTo(x - normal.x * (roadWidth / 2 - 4), y - normal.y * (roadWidth / 2 - 4));
      context.lineTo(x + normal.x * (roadWidth / 2 - 4), y + normal.y * (roadWidth / 2 - 4));
      context.strokeStyle = "rgba(232,238,242,.78)"; context.lineWidth = 2; context.stroke();
    }
  }
  context.beginPath(); context.arc(center.x, center.y, coreRadius, 0, Math.PI * 2);
  context.fillStyle = "#344b55"; context.fill();
  const ports = lanePortLayout(node, center, coreRadius + 5);
  for (const assignment of node.roadBundleAssignments ?? []) {
    for (const match of assignment.laneAssignments ?? []) {
      const a = ports.get(match.fromLaneId); const b = ports.get(match.toLaneId);
      if (a && b) drawBezier(context, a, b, center, "#51c98b", 3);
    }
  }
  for (const arm of node.arms) {
    for (const laneId of arm.laneIds) {
      const point = ports.get(laneId);
      const incoming = arm.incomingLaneIds.includes(laneId);
      const outgoing = arm.outgoingLaneIds.includes(laneId);
      context.beginPath(); context.arc(point.x, point.y, 5, 0, Math.PI * 2);
      context.fillStyle = incoming && outgoing ? "#e8eef2" : incoming ? "#e9b949" : "#22c3d6";
      context.fill();
    }
  }
}

function renderNodeList() {
  const nodes = filteredNodes();
  elements.nodeCount.textContent = `${nodes.length} / ${state.template.nodes.length}`;
  elements.nodeList.replaceChildren();
  for (const node of nodes) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `node-item${node.nodeId === state.selectedNodeId ? " active" : ""}`;
    const text = document.createElement("span");
    const strong = document.createElement("strong"); strong.textContent = node.nodeId;
    const small = document.createElement("small"); small.textContent = `${node.armCount} 个道路方向 · ${node.roadBundleAssignments.length} 组候选`;
    text.append(strong, small);
    const type = document.createElement("span"); type.className = "node-type";
    const audit = state.solverReport?.nodes.find((item) => item.nodeId === node.nodeId);
    if (audit?.conflictCount) { type.textContent = `${audit.conflictCount} 冲突`; type.classList.add("conflict"); }
    else if (audit?.complete) { type.textContent = "已闭合"; type.classList.add("complete"); }
    else if (audit) type.textContent = `${audit.freedomCount} 自由度`;
    else type.textContent = classificationLabel(node.classification);
    button.append(text, type);
    button.addEventListener("click", () => setSelectedNode(node.nodeId));
    elements.nodeList.append(button);
  }
  if (!nodes.length) {
    const empty = document.createElement("p"); empty.className = "empty-state"; empty.textContent = "当前筛选没有节点";
    elements.nodeList.append(empty);
  }
}

function renderSolverReport() {
  const report = state.solverReport;
  elements.solverReport.hidden = !report;
  if (!report) return;
  const node = report.nodes.find((item) => item.nodeId === state.selectedNodeId);
  elements.solverReport.className = `solver-report${report.conflictCount ? " conflict" : report.uncoveredLanePortCount ? "" : " complete"}`;
  elements.solverReport.replaceChildren();
  const title = document.createElement("strong");
  title.textContent = report.conflictCount ? `${report.conflictCount} 个冲突待处理` : report.uncoveredLanePortCount ? `${report.uncoveredLanePortCount} 个车道端口未闭合` : "当前匹配已闭合";
  const overall = document.createElement("span"); overall.textContent = `${report.completeNodeCount}/${report.nodeCount} 个节点闭合`;
  elements.solverReport.append(title, overall);
  if (node && !node.complete) {
    const detail = document.createElement("span"); detail.style.display = "block";
    detail.textContent = `${node.nodeId}：${node.freedomCount} 自由度，${node.emptyCandidateCount} 条空路线候选${node.conflicts.length ? `，${node.conflicts.join("；")}` : ""}`;
    elements.solverReport.append(detail);
  }
}

function renderAssignmentOptions() {
  const node = currentNode();
  elements.assignmentSelect.replaceChildren();
  for (const assignment of node?.roadBundleAssignments ?? []) {
    const option = document.createElement("option");
    option.value = assignment.id;
    option.textContent = `${assignment.fromRoadBundleId} → ${assignment.toRoadBundleId}`;
    option.selected = assignment.id === state.selectedAssignmentId;
    elements.assignmentSelect.append(option);
  }
  elements.assignmentSelect.disabled = !node?.roadBundleAssignments.length;
}

function laneButton(laneId, side, assignment) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "lane-button";
  button.dataset.laneId = laneId;
  button.dataset.side = side;
  const lane = findLane(laneId);
  const name = document.createElement("span"); name.textContent = laneId;
  const arrow = document.createElement("small"); arrow.textContent = side === "incoming" ? "进入" : "驶出";
  button.append(name, arrow);
  const matched = assignment.laneAssignments?.some((item) => side === "incoming" ? item.fromLaneId === laneId : item.toLaneId === laneId);
  if (matched) button.classList.add("matched");
  if (side === "incoming" && state.pendingIncomingLaneId === laneId) button.classList.add("selected");
  button.title = lane ? `${lane.name} · ${lane.markings.leftBoundary}/${lane.markings.rightBoundary}` : laneId;
  button.addEventListener("click", () => {
    if (side === "incoming") {
      state.pendingIncomingLaneId = state.pendingIncomingLaneId === laneId ? null : laneId;
      renderMatcher();
      return;
    }
    if (!state.pendingIncomingLaneId) {
      elements.saveStatus.textContent = "先选择入口车道";
      return;
    }
    toggleLaneMatch(assignment, state.pendingIncomingLaneId, laneId);
    saveLocal();
    render();
  });
  return button;
}

function renderMatcher() {
  const node = currentNode();
  const assignment = currentAssignment();
  elements.incomingLanes.replaceChildren();
  elements.outgoingLanes.replaceChildren();
  elements.matchList.replaceChildren();
  if (!assignment) {
    elements.assignmentMeta.textContent = node?.assignmentPolicy === "road_port_only" ? "该节点按混沌路口处理，只保留道路端口，不进行车道匹配。" : "没有可匹配的道路束。";
    elements.clearAssignmentButton.disabled = true;
    elements.suggestAssignmentButton.disabled = true;
    requestAnimationFrame(drawMatchLines);
    return;
  }
  elements.clearAssignmentButton.disabled = false;
  elements.suggestAssignmentButton.disabled = false;
  elements.assignmentMeta.replaceChildren();
  const mode = document.createElement("strong"); mode.textContent = assignment.suggestedMode;
  elements.assignmentMeta.append("建议模式：", mode, ` · ${assignment.incomingLaneIds.length} 条入口 → ${assignment.outgoingLaneIds.length} 条出口`);
  for (const laneId of assignment.incomingLaneIds) elements.incomingLanes.append(laneButton(laneId, "incoming", assignment));
  for (const laneId of assignment.outgoingLaneIds) elements.outgoingLanes.append(laneButton(laneId, "outgoing", assignment));
  for (const match of assignment.laneAssignments ?? []) {
    const row = document.createElement("div"); row.className = "match-row";
    const from = document.createElement("span"); from.textContent = match.fromLaneId;
    const arrow = document.createElement("span"); arrow.textContent = "→";
    const to = document.createElement("span"); to.textContent = match.toLaneId;
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×"; remove.title = "删除匹配";
    remove.addEventListener("click", () => { toggleLaneMatch(assignment, match.fromLaneId, match.toLaneId); saveLocal(); render(); });
    row.append(from, arrow, to, remove); elements.matchList.append(row);
  }
  if (!assignment.laneAssignments?.length) {
    const empty = document.createElement("p"); empty.className = "empty-state"; empty.textContent = "选择入口车道，再选择出口车道建立匹配";
    elements.matchList.append(empty);
  }
  requestAnimationFrame(drawMatchLines);
}

function renderDirectionEditor() {
  const node = currentNode();
  elements.directionList.replaceChildren();
  if (!node) return;
  for (const arm of node.arms) {
    const section = document.createElement("section"); section.className = "direction-arm";
    const heading = document.createElement("h3"); heading.textContent = `${arm.otherNodeId} · ${arm.roadBundleId}`;
    section.append(heading);
    for (const laneId of arm.laneIds) {
      const lane = findLane(laneId);
      const reversed = state.reversedLaneIds.has(laneId);
      const source = reversed ? lane.traffic.targetNodeId : lane.traffic.sourceNodeId;
      const target = reversed ? lane.traffic.sourceNodeId : lane.traffic.targetNodeId;
      const incoming = arm.incomingLaneIds.includes(laneId);
      const outgoing = arm.outgoingLaneIds.includes(laneId);
      const role = incoming && outgoing ? "双向" : incoming ? "入口" : outgoing ? "出口" : "未连接";
      const row = document.createElement("div"); row.className = `direction-row${reversed ? " reversed" : ""}`;
      const content = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = laneId;
      const details = document.createElement("small"); details.textContent = `${source} → ${target}`;
      const roleText = document.createElement("small"); roleText.className = "role"; roleText.textContent = `${role}${reversed ? " · 已校正反向" : " · 原始方向"}`;
      content.append(title, details, roleText);
      const reverse = document.createElement("button"); reverse.type = "button"; reverse.textContent = reversed ? "恢复" : "反向";
      reverse.addEventListener("click", () => {
        if (reversed) state.reversedLaneIds.delete(laneId); else state.reversedLaneIds.add(laneId);
        rebuildDirections(state.template, state.road, state.reversedLaneIds);
        const assignments = currentNode()?.roadBundleAssignments ?? [];
        if (!assignments.some((item) => item.id === state.selectedAssignmentId)) state.selectedAssignmentId = assignments[0]?.id ?? null;
        state.pendingIncomingLaneId = null;
        saveLocal(); render();
      });
      row.append(content, reverse); section.append(row);
    }
    elements.directionList.append(section);
  }
}

function drawMatchLines() {
  const assignment = currentAssignment();
  elements.matchLines.replaceChildren();
  if (!assignment) return;
  const stageRect = elements.matcherStage.getBoundingClientRect();
  elements.matchLines.setAttribute("viewBox", `0 0 ${stageRect.width} ${stageRect.height}`);
  for (const match of assignment.laneAssignments ?? []) {
    const from = elements.incomingLanes.querySelector(`[data-lane-id="${CSS.escape(match.fromLaneId)}"]`);
    const to = elements.outgoingLanes.querySelector(`[data-lane-id="${CSS.escape(match.toLaneId)}"]`);
    if (!from || !to) continue;
    const a = from.getBoundingClientRect(); const b = to.getBoundingClientRect();
    const x1 = a.right - stageRect.left; const y1 = a.top + a.height / 2 - stageRect.top;
    const x2 = b.left - stageRect.left; const y2 = b.top + b.height / 2 - stageRect.top;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`);
    path.setAttribute("fill", "none"); path.setAttribute("stroke", "#51c98b"); path.setAttribute("stroke-width", "2");
    elements.matchLines.append(path);
  }
}

function render() {
  const node = currentNode();
  renderNodeList(); renderWorldCanvas(); renderAssignmentOptions(); renderNodeCanvas(); renderMatcher(); renderDirectionEditor(); renderSolverReport();
  elements.matchingView.hidden = state.editorTab !== "matching";
  elements.directionView.hidden = state.editorTab !== "direction";
  elements.matchingTab.setAttribute("aria-selected", String(state.editorTab === "matching"));
  elements.directionTab.setAttribute("aria-selected", String(state.editorTab === "direction"));
  elements.nodeSubtitle.textContent = node ? `${node.armCount} 个道路方向 · ${node.position.x}, ${node.position.y}` : "";
  elements.classificationBadge.textContent = node ? classificationLabel(node.classification) : "";
  elements.classificationBadge.className = `badge ${node?.assignmentPolicy === "manual_road_bundle_mapping" ? "review" : "chaotic"}`;
}

function exportConfirmed() {
  const data = buildConfirmedExport(state.template, state.road, state.reversedLaneIds);
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob); link.download = "confirmed-node-flow.v1.json"; link.click();
  URL.revokeObjectURL(link.href);
}

async function importConfirmed(file) {
  restoreConfirmed(JSON.parse(await file.text()));
  state.solverReport = analyzeFlowMatching(state.template);
  saveLocal(); render();
}

function applyAndValidate() {
  const applied = applyDeterministicMatches(state.template);
  state.solverReport = analyzeFlowMatching(state.template);
  saveLocal(); render();
  elements.saveStatus.textContent = applied.autoAddedMatchCount ? `自动新增 ${applied.autoAddedMatchCount} 条` : "校验完成";
}

document.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => {
  state.filter = button.dataset.filter;
  document.querySelectorAll("[data-filter]").forEach((item) => item.classList.toggle("active", item === button));
  const nodes = filteredNodes();
  if (!nodes.some((item) => item.nodeId === state.selectedNodeId)) setSelectedNode(nodes[0]?.nodeId ?? null);
  else render();
}));
elements.assignmentSelect.addEventListener("change", () => { state.selectedAssignmentId = elements.assignmentSelect.value; state.pendingIncomingLaneId = null; render(); });
elements.clearAssignmentButton.addEventListener("click", () => { const assignment = currentAssignment(); if (assignment) { assignment.laneAssignments = []; saveLocal(); render(); } });
elements.suggestAssignmentButton.addEventListener("click", () => { const assignment = currentAssignment(); if (assignment) { assignment.laneAssignments = suggestSpatialMatches(currentNode(), assignment); saveLocal(); render(); } });
elements.exportButton.addEventListener("click", exportConfirmed);
elements.applyButton.addEventListener("click", applyAndValidate);
elements.matchingTab.addEventListener("click", () => { state.editorTab = "matching"; render(); });
elements.directionTab.addEventListener("click", () => { state.editorTab = "direction"; render(); });
elements.importButton.addEventListener("click", () => elements.importInput.click());
elements.importInput.addEventListener("change", () => { if (elements.importInput.files[0]) importConfirmed(elements.importInput.files[0]).catch(showError); });
window.addEventListener("resize", () => { renderWorldCanvas(); renderNodeCanvas(); drawMatchLines(); });

function showError(error) {
  elements.loadStatus.textContent = `加载失败：${error.message}`;
  console.error(error);
}

async function load() {
  const [templateResponse, roadResponse, confirmedResponse] = await Promise.all([fetch(TEMPLATE_URL), fetch(ROAD_URL), fetch(CONFIRMED_URL)]);
  if (!templateResponse.ok || !roadResponse.ok) throw new Error("无法读取分析 JSON，请通过本地服务器打开页面");
  state.template = await templateResponse.json(); state.road = await roadResponse.json();
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved) restoreConfirmed(JSON.parse(saved));
  else if (confirmedResponse.ok) restoreConfirmed(await confirmedResponse.json());
  state.solverReport = analyzeFlowMatching(state.template);
  state.selectedNodeId = filteredNodes()[0]?.nodeId ?? state.template.nodes[0]?.nodeId;
  state.selectedAssignmentId = currentNode()?.roadBundleAssignments[0]?.id ?? null;
  elements.loadStatus.textContent = `${state.template.summary.manualReviewNodeCount} 个节点待匹配 · ${state.template.summary.chaoticNodeCount} 个混沌路口`;
  render();
}

load().catch(showError);
