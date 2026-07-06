import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Play, Square, RefreshCcw, Wifi, WifiOff, Server, Camera } from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

const EXAMPLES = [
  { label: "手机 MJPEG", value: "http://手机IP:8080/video" },
  { label: "手机 RTSP", value: "rtsp://手机IP:8554/live" },
  { label: "电脑摄像头", value: "0" },
  { label: "本地视频", value: "data/demo_traffic.mp4" },
];

function formatResolution(status) {
  if (!status.frame_width || !status.frame_height) return "--";
  return `${status.frame_width} x ${status.frame_height}`;
}

function StatusPill({ connected }) {
  return (
    <span className={connected ? "status-pill online" : "status-pill offline"}>
      {connected ? <Wifi size={15} /> : <WifiOff size={15} />}
      {connected ? "已连接" : "未连接"}
    </span>
  );
}

function App() {
  const [source, setSource] = useState("http://手机IP:8080/video");
  const [status, setStatus] = useState({
    running: false,
    connected: false,
    frames_received: 0,
    fps: 0,
  });
  const [streamKey, setStreamKey] = useState(Date.now());
  const [logs, setLogs] = useState(["等待输入手机视频流地址"]);
  const [busy, setBusy] = useState(false);

  const streamUrl = useMemo(() => `${API_BASE}/api/video/mjpeg?ts=${streamKey}`, [streamKey]);

  async function fetchStatus() {
    try {
      const res = await fetch(`${API_BASE}/api/video/status`);
      const data = await res.json();
      setStatus(data);
    } catch {
      setStatus((prev) => ({
        ...prev,
        connected: false,
        last_error: "无法连接后端服务，请确认 FastAPI 已启动",
      }));
    }
  }

  function pushLog(message) {
    const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setLogs((prev) => [`${time}  ${message}`, ...prev].slice(0, 8));
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
      const data = await res.json();
      setStatus(data);
      pushLog("已停止视频流");
    } catch {
      pushLog("停止失败：无法连接后端服务");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    fetchStatus();
    const timer = window.setInterval(fetchStatus, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark"><Camera size={22} /></span>
          <div>
            <h1>STrans 视频接入测试台</h1>
            <p>手机摄像头 / ESP32-CAM / RTSP / 本地摄像头实时传输验证</p>
          </div>
        </div>
        <StatusPill connected={Boolean(status.connected)} />
      </header>

      <section className="workspace">
        <section className="video-panel">
          <div className="video-toolbar">
            <div>
              <strong>实时画面</strong>
              <span>{status.source || "尚未启动视频源"}</span>
            </div>
            <button className="icon-button" type="button" onClick={() => setStreamKey(Date.now())} title="刷新画面">
              <RefreshCcw size={18} />
            </button>
          </div>

          <div className="video-frame">
            {status.running || status.connected ? (
              <img src={streamUrl} alt="实时视频流" />
            ) : (
              <div className="empty-state">
                <Camera size={44} />
                <h2>等待视频输入</h2>
                <p>输入手机 App 的 MJPEG/RTSP 地址，然后点击启动。</p>
              </div>
            )}
          </div>
        </section>

        <aside className="side-panel">
          <section className="control-block">
            <h2>视频源</h2>
            <label htmlFor="source">流地址或摄像头编号</label>
            <input
              id="source"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              placeholder="http://192.168.1.23:8080/video"
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
          </section>

          <section className="metric-block">
            <h2>服务状态</h2>
            <div className="metric-row">
              <span>后端地址</span>
              <strong>{API_BASE.replace("http://", "")}</strong>
            </div>
            <div className="metric-row">
              <span>运行状态</span>
              <strong>{status.running ? "运行中" : "已停止"}</strong>
            </div>
            <div className="metric-row">
              <span>分辨率</span>
              <strong>{formatResolution(status)}</strong>
            </div>
            <div className="metric-row">
              <span>FPS</span>
              <strong>{status.fps || 0}</strong>
            </div>
            <div className="metric-row">
              <span>已接收帧</span>
              <strong>{status.frames_received || 0}</strong>
            </div>
            {status.last_error && <div className="error-box">{status.last_error}</div>}
          </section>

          <section className="log-block">
            <h2><Server size={18} />事件日志</h2>
            <ul>
              {logs.map((log, index) => (
                <li key={`${log}-${index}`}>{log}</li>
              ))}
            </ul>
          </section>
        </aside>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
