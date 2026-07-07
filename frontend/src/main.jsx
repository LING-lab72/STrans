import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  BarChart3,
  Camera,
  Car,
  CheckCircle2,
  CircleDot,
  Cpu,
  Database,
  Gauge,
  Layers,
  Map,
  ParkingCircle,
  Play,
  RefreshCcw,
  Route,
  Settings2,
  ShieldCheck,
  Square,
  TrafficCone,
  TriangleAlert,
  Wifi,
  WifiOff,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const EXAMPLES = [
  { label: "手机 MJPEG", value: "http://192.168.110.13:8080/video" },
  { label: "手机 RTSP", value: "rtsp://手机IP:8554/live" },
  { label: "电脑摄像头", value: "0" },
  { label: "沙盘视频", value: "data/sandtable_overview.mp4" },
  { label: "通用视频", value: "data/demo_traffic.mp4" },
];

const CAMERA_TILES = [
  { title: "沙盘全景", icon: <Map size={16} />, tone: "sky" },
  { title: "闸机入口", icon: <ShieldCheck size={16} />, tone: "green" },
  { title: "停车区域", icon: <ParkingCircle size={16} />, tone: "amber" },
  { title: "路口视角", icon: <TrafficCone size={16} />, tone: "rose" },
];

const DEFAULT_STATUS = {
  running: false,
  connected: false,
  frames_received: 0,
  fps: 0,
};

function cnCongestion(level) {
  return { low: "畅通", medium: "缓行", high: "拥堵" }[level] || "--";
}

function severityText(severity) {
  return { info: "提示", warning: "警告", critical: "严重" }[severity] || severity;
}

function formatResolution(status) {
  if (!status.frame_width || !status.frame_height) return "--";
  return `${status.frame_width} x ${status.frame_height}`;
}

function StatusPill({ connected }) {
  return (
    <span className={connected ? "status-pill online" : "status-pill offline"}>
      {connected ? <Wifi size={15} /> : <WifiOff size={15} />}
      {connected ? "视频接入中" : "等待接入"}
    </span>
  );
}

function Panel({ title, icon, children, action, className = "" }) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-title">
        <span>
          {icon}
          {title}
        </span>
        {action}
      </header>
      {children}
    </section>
  );
}

function StatBlock({ label, value, hint, icon, tone = "blue" }) {
  return (
    <div className={`stat-block ${tone}`}>
      <span className="stat-icon">{icon}</span>
      <div>
        <p>{label}</p>
        <strong>{value}</strong>
        {hint && <small>{hint}</small>}
      </div>
    </div>
  );
}

function CameraTile({ tile, active }) {
  return (
    <div className={`camera-tile ${tile.tone} ${active ? "active" : ""}`}>
      <header>
        <span>{tile.icon}</span>
        <strong>{tile.title}</strong>
      </header>
      <div className="tile-map">
        <i className="road horizontal" />
        <i className="road vertical" />
        <i className="vehicle one" />
        <i className="vehicle two" />
        <i className="poi" />
      </div>
      <footer>{active ? "主画面" : "待接入"}</footer>
    </div>
  );
}

function MiniProgress({ label, value, tone = "blue" }) {
  return (
    <div className="mini-progress">
      <div>
        <span>{label}</span>
        <strong>{value}%</strong>
      </div>
      <i>
        <b className={tone} style={{ width: `${Math.min(100, Math.max(0, value))}%` }} />
      </i>
    </div>
  );
}

function App() {
  const [source, setSource] = useState("http://192.168.110.13:8080/video");
  const [status, setStatus] = useState(DEFAULT_STATUS);
  const [dashboard, setDashboard] = useState(null);
  const [devices, setDevices] = useState([]);
  const [models, setModels] = useState({ current_model: "mock", models: [] });
  const [analysis, setAnalysis] = useState(null);
  const [history, setHistory] = useState([]);
  const [whitelist, setWhitelist] = useState([]);
  const [plateInput, setPlateInput] = useState("A001");
  const [gateDecision, setGateDecision] = useState(null);
  const [streamKey, setStreamKey] = useState(Date.now());
  const [logs, setLogs] = useState(["等待视频源接入"]);
  const [busy, setBusy] = useState(false);

  const streamUrl = useMemo(() => `${API_BASE}/api/video/mjpeg?ts=${streamKey}`, [streamKey]);
  const fallbackStats = {
    count_in: 0,
    count_out: 0,
    current_count: 0,
    density: 0,
    avg_speed: 0,
    congestion_level: "low",
  };
  const stats = analysis?.model_id === "yolov8n" && analysis?.traffic_stats
    ? analysis.traffic_stats
    : dashboard?.stats || fallbackStats;
  const system = dashboard?.system || {};
  const events = dashboard?.events || [];
  const detections = analysis?.detections || [];
  const congestionValue = Math.round((Number(stats.density) || 0) * 100);
  const fpsValue = Math.round(Number(status.fps) || 0);

  function pushLog(message) {
    const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setLogs((prev) => [`${time}  ${message}`, ...prev].slice(0, 10));
  }

  async function getJson(path, setter) {
    const res = await fetch(`${API_BASE}${path}`);
    if (!res.ok) throw new Error(path);
    setter(await res.json());
  }

  async function refreshAll() {
    try {
      await Promise.all([
        getJson("/api/video/status", setStatus),
        getJson("/api/dashboard", setDashboard),
        getJson("/api/devices", setDevices),
        getJson("/api/models", setModels),
        getJson("/api/analysis/latest", setAnalysis),
        getJson("/api/analysis/history", setHistory),
        getJson("/api/whitelist", setWhitelist),
      ]);
    } catch {
      setStatus((prev) => ({
        ...prev,
        connected: false,
        last_error: "无法连接后端服务，请确认 FastAPI 已启动",
      }));
    }
  }

  async function startStream() {
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/video/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source }),
      });
      const data = await res.json();
      setStatus(data);
      setStreamKey(Date.now());
      pushLog(`启动视频源：${source}`);
      await refreshAll();
    } catch {
      pushLog("启动失败：无法连接后端服务");
    } finally {
      setBusy(false);
    }
  }

  async function stopStream() {
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/video/stop`, { method: "POST" });
      setStatus(await res.json());
      pushLog("已停止视频流");
      await refreshAll();
    } catch {
      pushLog("停止失败：无法连接后端服务");
    } finally {
      setBusy(false);
    }
  }

  async function selectModel(modelId) {
    await fetch(`${API_BASE}/api/models/current`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: modelId }),
    });
    pushLog(`模型切换为：${modelId}`);
    await refreshAll();
  }

  async function decideGate() {
    const identity = plateInput.trim();
    if (!identity) return;
    const res = await fetch(`${API_BASE}/api/whitelist/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        plate_no: identity.includes("-") || /[\u4e00-\u9fa5]/.test(identity) ? identity : null,
        electronic_id: identity.includes("-") || /^[A-Z]\d+/.test(identity) ? identity : null,
        confidence: 0.92,
      }),
    });
    const data = await res.json();
    setGateDecision(data);
    pushLog(`闸机决策：${identity} -> ${data.gate_action === "allow" ? "允许通行" : "拒绝通行"}`);
    await refreshAll();
  }

  function renderDetections() {
    if (!detections.length || !analysis?.source_width || !analysis?.source_height) return null;
    return detections.map((det, index) => {
      const [x1, y1, x2, y2] = det.bbox;
      const style = {
        left: `${(x1 / analysis.source_width) * 100}%`,
        top: `${(y1 / analysis.source_height) * 100}%`,
        width: `${((x2 - x1) / analysis.source_width) * 100}%`,
        height: `${((y2 - y1) / analysis.source_height) * 100}%`,
      };
      return (
        <div className={`detect-box ${det.class}`} style={style} key={`${det.class}-${index}-${det.confidence}`}>
          <span>{det.class} {Math.round(det.confidence * 100)}%</span>
        </div>
      );
    });
  }

  useEffect(() => {
    refreshAll();
    const timer = window.setInterval(refreshAll, 700);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className="screen-shell">
      <header className="screen-header">
        <div className="brand">
          <span className="brand-mark"><Route size={25} /></span>
          <div>
            <h1>STrans 智慧交通沙盘大屏</h1>
            <p>沙盘全景监控 · 车辆检测追踪 · 拥堵态势研判 · 闸机联动验证</p>
          </div>
        </div>
        <div className="header-center">
          <span><CircleDot size={14} /> 实时监控</span>
          <span>{new Date().toLocaleDateString("zh-CN")}</span>
        </div>
        <StatusPill connected={Boolean(status.connected)} />
      </header>

      <section className="overview-strip">
        <StatBlock icon={<Car size={20} />} label="当前车辆" value={stats.current_count} hint={`累计进入 ${stats.count_in}`} />
        <StatBlock icon={<Gauge size={20} />} label="平均速度" value={`${stats.avg_speed || 0} km/h`} hint={`出场 ${stats.count_out}`} tone="cyan" />
        <StatBlock
          icon={<TriangleAlert size={20} />}
          label="拥堵等级"
          value={cnCongestion(stats.congestion_level)}
          hint={`密度 ${stats.density}`}
          tone={stats.congestion_level === "high" ? "red" : stats.congestion_level === "medium" ? "amber" : "green"}
        />
        <StatBlock icon={<Activity size={20} />} label="视频帧率" value={`${fpsValue} FPS`} hint={`${status.frames_received || 0} 帧`} tone="violet" />
        <StatBlock icon={<Cpu size={20} />} label="系统负载" value={`${system.cpu_percent ?? "--"}%`} hint={`内存 ${system.memory_percent ?? "--"}%`} tone="slate" />
      </section>

      <section className="dashboard-grid">
        <aside className="left-stack">
          <Panel title="车流统计" icon={<BarChart3 size={18} />}>
            <div className="flow-total">
              <strong>{Number(stats.count_in || 0) + Number(stats.count_out || 0)}</strong>
              <span>累计通行</span>
            </div>
            <div className="split-stats">
              <span><b>{stats.count_in}</b>驶入</span>
              <span><b>{stats.count_out}</b>驶出</span>
            </div>
            <div className="history-chart">
              {history.slice(-12).map((item) => (
                <div className="bar-item" key={item.timestamp}>
                  <span style={{ height: `${Math.max(12, item.vehicle_count * 9)}px` }} />
                  <small>{item.timestamp}</small>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="拥堵热力" icon={<Gauge size={18} />}>
            <MiniProgress label="主干道" value={Math.max(12, congestionValue)} tone="blue" />
            <MiniProgress label="闸机入口" value={stats.congestion_level === "high" ? 82 : 36} tone="amber" />
            <MiniProgress label="停车区域" value={stats.current_count > 3 ? 68 : 24} tone="green" />
            <div className={`congestion-badge ${stats.congestion_level}`}>
              <strong>{cnCongestion(stats.congestion_level)}</strong>
              <span>当前沙盘运行状态</span>
            </div>
          </Panel>

          <Panel title="设备状态" icon={<Layers size={18} />}>
            <div className="device-list">
              {devices.map((device) => (
                <button key={device.device_id} type="button" onClick={() => setSource(device.stream_url)}>
                  <span>
                    <strong>{device.name}</strong>
                    <small>{device.location}</small>
                  </span>
                  <em className={device.status}>{device.status}</em>
                </button>
              ))}
            </div>
          </Panel>
        </aside>

        <section className="center-stage">
          <Panel
            title="沙盘全景"
            icon={<Camera size={18} />}
            className="stage-panel"
            action={
              <button className="icon-button" type="button" onClick={() => setStreamKey(Date.now())} title="刷新画面">
                <RefreshCcw size={18} />
              </button>
            }
          >
            <div className="video-meta">
              <span>{status.source || "尚未启动视频源"}</span>
              <span>{formatResolution(status)} · {fpsValue} FPS · 检测 {detections.length} 个目标</span>
            </div>
            <div className="video-frame">
              {status.running || status.connected ? (
                <>
                  <img src={streamUrl} alt="实时视频流" />
                  {renderDetections()}
                  <div className="heatmap-dot one" />
                  <div className="heatmap-dot two" />
                  <div className="stage-watermark">STrans LIVE</div>
                </>
              ) : (
                <div className="empty-state">
                  <Camera size={44} />
                  <h2>等待沙盘视频输入</h2>
                  <p>可接入 IP Webcam、电脑摄像头或本地沙盘视频进行演示。</p>
                </div>
              )}
            </div>
          </Panel>

          <div className="camera-grid">
            {CAMERA_TILES.map((tile, index) => (
              <CameraTile key={tile.title} tile={tile} active={index === 0 && Boolean(status.connected)} />
            ))}
          </div>
        </section>

        <aside className="right-stack">
          <Panel title="视频源接入" icon={<Wifi size={18} />}>
            <label htmlFor="source">流地址或摄像头编号</label>
            <input
              id="source"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="http://192.168.110.13:8080/video"
            />
            <div className="example-grid">
              {EXAMPLES.map((example) => (
                <button key={example.label} type="button" onClick={() => setSource(example.value)}>
                  {example.label}
                </button>
              ))}
            </div>
            <div className="actions">
              <button className="primary" type="button" onClick={startStream} disabled={busy || !source.trim()}>
                <Play size={18} />
                启动
              </button>
              <button className="secondary" type="button" onClick={stopStream} disabled={busy}>
                <Square size={18} />
                停止
              </button>
            </div>
            {status.last_error && <div className="error-box">{status.last_error}</div>}
          </Panel>

          <Panel title="模型状态" icon={<Settings2 size={18} />}>
            <div className="model-list">
              {models.models.map((model) => (
                <button
                  className={models.current_model === model.model_id ? "selected" : ""}
                  key={model.model_id}
                  type="button"
                  onClick={() => selectModel(model.model_id)}
                >
                  <span>
                    <strong>{model.name}</strong>
                    <small>{model.description}</small>
                  </span>
                  <em>{model.status}</em>
                </button>
              ))}
            </div>
            {analysis?.model_id === "yolov8n" && (
              <div className="analysis-note">
                <strong>本地 YOLO</strong>
                <span>
                  {analysis.error
                    ? analysis.error
                    : `检测 ${detections.length} 个目标 · ${analysis.inference_ms || 0} ms`}
                </span>
              </div>
            )}
          </Panel>

          <Panel title="闸机决策" icon={<ShieldCheck size={18} />}>
            <div className="gate-form">
              <input value={plateInput} onChange={(event) => setPlateInput(event.target.value)} placeholder="车牌或电子 ID，如 A001" />
              <button className="primary compact" type="button" onClick={decideGate}>
                <CheckCircle2 size={17} />
                判定
              </button>
            </div>
            {gateDecision && (
              <div className={`decision ${gateDecision.gate_action}`}>
                <strong>{gateDecision.gate_action === "allow" ? "允许通行" : "拒绝通行"}</strong>
                <span>{gateDecision.reason}</span>
              </div>
            )}
            <div className="whitelist">
              {whitelist.slice(0, 5).map((item) => (
                <span key={item.identity}>{item.identity}</span>
              ))}
            </div>
          </Panel>

          <Panel title="事件告警" icon={<TriangleAlert size={18} />}>
            <ul className="event-list">
              {events.slice(0, 5).map((event) => (
                <li className={event.severity} key={event.event_id}>
                  <strong>{severityText(event.severity)}</strong>
                  <span>{event.description}</span>
                  <time>{event.created_at?.replace("T", " ")}</time>
                </li>
              ))}
            </ul>
          </Panel>
        </aside>
      </section>

      <section className="bottom-timeline">
        <div className="timeline-title">
          <Database size={17} />
          <strong>运行日志</strong>
        </div>
        <div className="timeline-items">
          {logs.map((log, index) => (
            <span key={`${log}-${index}`}>{log}</span>
          ))}
        </div>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
