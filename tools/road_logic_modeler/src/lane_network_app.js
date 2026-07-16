import { analyzeFlowMatching, applyDeterministicMatches, compilePhysicalLaneNetwork, rebuildDirections } from "./flow_matcher_model.js";

const URLS = {
  road: "./analysis/baseline/road_logic_model (4).road-lane.v1.json",
  template: "./analysis/node-flow-template.v1.json",
  confirmed: "./confirmed-node-flow.v1.json",
};
const STORAGE_KEY = "road_logic_modeler.confirmed-node-flow.v1";
const canvas = document.getElementById("networkCanvas");
const context = canvas.getContext("2d");
const state = { road:null, template:null, network:null, audit:null, scale:1, offsetX:0, offsetY:0, dragging:false, last:null, dragStart:null, selectedNodeId:null };
const controls = Object.fromEntries(["showDirections","showConnections","showIssues","fitButton","status","summary","details"].map((id) => [id, document.getElementById(id)]));

function restore(payload) {
  const reversed = new Set((payload.laneDirectionOverrides ?? []).map((item) => item.laneId));
  rebuildDirections(state.template, state.road, reversed);
  for (const savedNode of payload.nodes ?? []) {
    const node = state.template.nodes.find((item) => item.nodeId === savedNode.nodeId);
    for (const saved of savedNode.roadBundleAssignments ?? []) {
      const assignment = node?.roadBundleAssignments.find((item) => item.id === saved.id);
      if (assignment) assignment.laneAssignments = (saved.laneAssignments ?? []).map((item) => ({ ...item }));
    }
  }
  applyDeterministicMatches(state.template);
  state.audit = analyzeFlowMatching(state.template);
  state.network = compilePhysicalLaneNetwork(state.template, state.road, reversed);
}

function resize() {
  const rect = canvas.getBoundingClientRect(); const ratio = Math.min(devicePixelRatio || 1, 2);
  canvas.width = Math.round(rect.width * ratio); canvas.height = Math.round(rect.height * ratio);
  context.setTransform(ratio,0,0,ratio,0,0); draw();
}
function fit() {
  const rect = canvas.getBoundingClientRect(); const pad = 55;
  state.scale = Math.min((rect.width-pad*2)/state.road.world.width,(rect.height-pad*2)/state.road.world.height);
  state.offsetX=(rect.width-state.road.world.width*state.scale)/2; state.offsetY=(rect.height-state.road.world.height*state.scale)/2; draw();
}
const screen = (p) => ({ x:state.offsetX+p.x*state.scale, y:state.offsetY+p.y*state.scale });
function strokePath(points,color,width) {
  context.beginPath(); points.forEach((point,index)=>{const p=screen(point); if(index)context.lineTo(p.x,p.y);else context.moveTo(p.x,p.y);}); context.strokeStyle=color; context.lineWidth=width; context.stroke();
}
function arrowOnLane(lane) {
  const points=lane.renderPath; let a=points[0],b=points.at(-1);
  const source=state.road.nodes.find((item)=>item.id===lane.effectiveTraffic.sourceNodeId);
  if(Math.hypot(b.x-source.position.x,b.y-source.position.y)<Math.hypot(a.x-source.position.x,a.y-source.position.y))[a,b]=[b,a];
  const p=screen({x:a.x+(b.x-a.x)*.58,y:a.y+(b.y-a.y)*.58}); const angle=Math.atan2(b.y-a.y,b.x-a.x);
  context.save();context.translate(p.x,p.y);context.rotate(angle);context.beginPath();context.moveTo(7,0);context.lineTo(-4,-4);context.lineTo(-4,4);context.closePath();context.fillStyle=lane.reversed?"#ebb94d":"#25c7d9";context.fill();context.restore();
}
function draw() {
  const rect=canvas.getBoundingClientRect(); context.clearRect(0,0,rect.width,rect.height); if(!state.network)return;
  for(const building of state.road.buildings){const p=screen({x:building.center.x-building.width/2,y:building.center.y-building.height/2}),width=building.width*state.scale,height=building.height*state.scale;context.fillStyle="#1b2931";context.strokeStyle="#4b606b";context.lineWidth=1;context.fillRect(p.x,p.y,width,height);context.strokeRect(p.x,p.y,width,height);if(width>70&&height>34){context.fillStyle="#728791";context.font="11px Segoe UI";context.fillText(building.name,p.x+7,p.y+16);}}
  for(const lane of state.network.lanes)strokePath(lane.renderPath,"#344952",Math.max(4,lane.width*state.scale*.72));
  for(const junction of state.network.junctions){const p=screen(junction.center);context.beginPath();context.arc(p.x,p.y,junction.radius*state.scale,0,Math.PI*2);context.fillStyle=junction.chaotic?"#3d535c":"#344952";context.fill();}
  if(controls.showConnections.checked)for(const link of state.network.connections){if(!link.rendered)continue;strokePath(link.path,"rgba(80,209,139,.92)",Math.max(1.2,1.8*state.scale));}
  for(const junction of state.network.junctions){if(!junction.chaotic)continue;const center=screen(junction.center);for(const arm of junction.approaches){const angle=arm.angleDegrees*Math.PI/180,normal={x:-Math.sin(angle),y:Math.cos(angle)};for(let stripe=0;stripe<5;stripe++){const along=(junction.radius+5+stripe*4)*state.scale,x=center.x+Math.cos(angle)*along,y=center.y+Math.sin(angle)*along,half=arm.width*state.scale*.43;context.beginPath();context.moveTo(x-normal.x*half,y-normal.y*half);context.lineTo(x+normal.x*half,y+normal.y*half);context.strokeStyle="rgba(238,243,245,.88)";context.lineWidth=Math.max(1.5,2.2*state.scale);context.stroke();}}}
  for(const lane of state.network.lanes){strokePath(lane.renderPath,lane.reversed?"#ebb94d":"#91aab4",Math.max(1,1.25*state.scale));if(controls.showDirections.checked)arrowOnLane(lane);}
  for(const node of state.template.nodes){const p=screen(node.position),audit=state.audit.nodes.find((item)=>item.nodeId===node.nodeId),issue=audit&&(audit.conflictCount||audit.freedomCount);context.beginPath();context.arc(p.x,p.y,node.nodeId===state.selectedNodeId?6:issue&&controls.showIssues.checked?4.5:2.4,0,Math.PI*2);context.fillStyle=node.nodeId===state.selectedNodeId?"#fff":issue&&controls.showIssues.checked?"#e96c77":"#4ed08a";context.fill();}
}
function selectAt(event){const rect=canvas.getBoundingClientRect();const x=(event.clientX-rect.left-state.offsetX)/state.scale,y=(event.clientY-rect.top-state.offsetY)/state.scale;let best=null;for(const node of state.template.nodes){const d=Math.hypot(node.position.x-x,node.position.y-y);if(d<18/state.scale&&(!best||d<best.d))best={node,d};}state.selectedNodeId=best?.node.nodeId??null;const audit=state.audit.nodes.find((item)=>item.nodeId===state.selectedNodeId);controls.summary.textContent=audit?`${audit.nodeId}：${audit.conflictCount} 个冲突，${audit.freedomCount} 个自由度，${audit.emptyCandidateCount} 条空候选`:`${state.network.lanes.length} 条车道 · ${state.network.connections.length} 条节点内连接 · ${state.audit.completeNodeCount}/${state.audit.nodeCount} 个节点闭合`;draw();}
canvas.addEventListener("wheel",(event)=>{event.preventDefault();const rect=canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,old=state.scale;state.scale=Math.max(.25,Math.min(4,state.scale*(event.deltaY<0?1.12:.89)));state.offsetX=x-(x-state.offsetX)*state.scale/old;state.offsetY=y-(y-state.offsetY)*state.scale/old;draw();},{passive:false});
canvas.addEventListener("pointerdown",(event)=>{state.dragging=true;state.last={x:event.clientX,y:event.clientY};state.dragStart={...state.last};canvas.classList.add("dragging");canvas.setPointerCapture(event.pointerId);});
canvas.addEventListener("pointermove",(event)=>{if(!state.dragging)return;state.offsetX+=event.clientX-state.last.x;state.offsetY+=event.clientY-state.last.y;state.last={x:event.clientX,y:event.clientY};draw();});
canvas.addEventListener("pointerup",(event)=>{const moved=Math.hypot(event.clientX-state.dragStart.x,event.clientY-state.dragStart.y);state.dragging=false;canvas.classList.remove("dragging");if(moved<3)selectAt(event);});
for(const id of ["showDirections","showConnections","showIssues"])controls[id].addEventListener("change",draw);controls.fitButton.addEventListener("click",fit);window.addEventListener("resize",resize);

async function load(){const [roadResponse,templateResponse,confirmedResponse]=await Promise.all([fetch(URLS.road),fetch(URLS.template),fetch(URLS.confirmed)]);state.road=await roadResponse.json();state.template=await templateResponse.json();const local=localStorage.getItem(STORAGE_KEY);restore(local?JSON.parse(local):await confirmedResponse.json());controls.status.textContent=`${state.network.lanes.length} 条车道 · ${state.network.summary.renderedConnectionCount} 条无交叉连续线`;controls.summary.textContent=`${state.audit.completeNodeCount}/${state.audit.nodeCount} 个待匹配节点闭合 · ${state.network.summary.logicalConnectionCount} 条逻辑连接 · ${state.network.summary.absorbedConnectionCount} 条冲突转向收进路口面`;resize();fit();}
load().catch((error)=>{controls.status.textContent=`加载失败：${error.message}`;console.error(error);});
