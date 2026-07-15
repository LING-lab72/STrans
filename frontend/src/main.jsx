import React, { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  BarChart3,
  Camera,
  CheckCircle2,
  Clock3,
  CloudSun,
  Cpu,
  Database,
  Download,
  Eye,
  FileText,
  Flame,
  MemoryStick,
  PackageCheck,
  Play,
  Radio,
  RefreshCcw,
  Route,
  ServerCog,
  Sparkles,
  Square,
  Trash2,
  X,
  Wifi,
  WifiOff,
} from "lucide-react";
import { Bell, KeyRound, Mic, Settings2, ShieldCheck, Users } from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const ROAD_MODELER_URL = "http://127.0.0.1:8765";
const DEFAULT_PHONE_URL = "http://192.168.110.13:8080/video";
const API_REQUEST_TIMEOUT_MS = 8000;
const FEATURE_VIEWS = new Set(["account", "analytics", "history", "incidents", "cameras", "whitelist", "models", "scheduler", "users", "audit", "roadmodeler"]);
const TREND_METRICS = {
  vehicle_count: { label: "车辆数量", shortLabel: "车辆", color: "#0f7aa5", tint: "#d9f2fb" },
  detection_count: { label: "检测框数量", shortLabel: "检测框", color: "#16856b", tint: "#dcf5ea" },
  event_count: { label: "事件数量", shortLabel: "事件", color: "#c76a16", tint: "#ffedd5" },
};
const TREND_LIMITS = [20, 50, 100];
const CAMERA_CHART_COLORS = ["#0f7aa5", "#16856b", "#c76a16", "#7559a6", "#d1495b", "#64748b"];

async function fetchWithTimeout(url, options = {}, timeoutMs = API_REQUEST_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("后端响应超时，请检查服务和摄像头连接");
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

const emptyAnalysis = {
  detections: [],
  traffic_stats: {
    vehicle_count: 0,
    current_count: 0,
    count_in: 0,
    count_out: 0,
    density: 0,
    avg_speed: null,
    congestion_level: "unknown",
  },
  events: [],
};

const emptyResources = {
  cpu: { usage_percent: 0 },
  memory: { usage_percent: 0, used_gb: 0, total_gb: 0 },
  gpu: { available: false, usage_percent: 0, memory_usage_percent: 0, memory_used_gb: 0, memory_total_gb: 0 },
  inference: { latest_ms: null },
};

const emptyWeather = {
  city: "北京",
  available: false,
  condition: "天气加载中",
  driving_advice: "正在获取北京实时天气。",
  travel_advice: "正在获取出行建议。",
  advice_level: "info",
};

function cx(...items) {
  return items.filter(Boolean).join(" ");
}

function congestionText(level) {
  return { low: "畅通", medium: "缓行", high: "拥堵", unknown: "待分析" }[level] || "待分析";
}

function statusText(status) {
  if (!status?.running) return status?.last_error ? "重连失败" : "未启动";
  if (status.connected) return "在线";
  return status?.last_error ? "自动重连中" : "连接中";
}

function algorithmStatusText(status) {
  return { not_configured: "本地模型", offline: "离线", ready: "已连接", error: "异常" }[status] || "本地模型";
}

function severityText(severity) {
  return { info: "提示", warning: "预警", critical: "严重" }[severity] || "提示";
}

function gateText(item) {
  if (item?.whitelist_status === true) return "可通过";
  if (item?.whitelist_status === false) return "需拦截";
  return "";
}

function uniqueEvents(events) {
  const seen = new Set();
  return events.filter((event) => {
    const key = `${event.type || ""}-${event.camera_id || ""}-${event.description || ""}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function usePolling(callback, delay) {
  useEffect(() => {
    callback();
    const timer = window.setInterval(callback, delay);
    return () => window.clearInterval(timer);
  }, [callback, delay]);
}

function Panel({ title, icon, action, children, className }) {
  return (
    <section className={cx("panel", className)}>
      <header className="panel-header">
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

function Metric({ label, value, hint, tone = "blue" }) {
  return (
    <div className={cx("metric", tone)}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  );
}

function formatTrendTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function DetectionTrendView({ records }) {
  const [metricKey, setMetricKey] = useState("vehicle_count");
  const [recordLimit, setRecordLimit] = useState(50);
  const metric = TREND_METRICS[metricKey];
  const chart = useMemo(() => {
    const width = 1000;
    const height = 340;
    const padding = { top: 24, right: 26, bottom: 52, left: 58 };
    const selected = records.slice(0, recordLimit).reverse();
    const values = selected.map((item) => Math.max(0, Number(item[metricKey]) || 0));
    const maxValue = Math.max(1, ...values);
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const baseline = padding.top + plotHeight;
    const points = selected.map((item, index) => {
      const value = values[index];
      const x = padding.left + (selected.length > 1 ? (index / (selected.length - 1)) * plotWidth : plotWidth / 2);
      const y = padding.top + plotHeight - (value / maxValue) * plotHeight;
      return { item, value, x, y };
    });
    let total = 0;
    let peak = 0;
    const cameraTotals = new Map();
    points.forEach((point) => {
      total += point.value;
      peak = Math.max(peak, point.value);
      const cameraName = point.item.camera_id || "未标记摄像头";
      cameraTotals.set(cameraName, (cameraTotals.get(cameraName) || 0) + point.value);
    });
    let cameraEntries = [...cameraTotals.entries()]
      .filter(([, value]) => value > 0)
      .sort((left, right) => right[1] - left[1]);
    if (cameraEntries.length > 6) {
      const otherTotal = cameraEntries.slice(5).reduce((sum, [, value]) => sum + value, 0);
      cameraEntries = [...cameraEntries.slice(0, 5), ["其他摄像头", otherTotal]];
    }
    const cameraTotal = cameraEntries.reduce((sum, [, value]) => sum + value, 0);
    let cameraOffset = 0;
    const cameraDistribution = cameraEntries.map(([name, value], index) => {
      const percentage = cameraTotal ? (value / cameraTotal) * 100 : 0;
      const entry = { name, value, percentage, offset: cameraOffset, color: CAMERA_CHART_COLORS[index] };
      cameraOffset += percentage;
      return entry;
    });
    const linePath = points.map((point, index) => `${index ? "L" : "M"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
    const areaPath = points.length
      ? `${linePath} L ${points.at(-1).x.toFixed(2)} ${baseline} L ${points[0].x.toFixed(2)} ${baseline} Z`
      : "";
    const labelIndexes = [...new Set([0, Math.floor((points.length - 1) / 4), Math.floor((points.length - 1) / 2), Math.floor(((points.length - 1) * 3) / 4), points.length - 1])]
      .filter((index) => index >= 0);
    return {
      width,
      height,
      padding,
      baseline,
      maxValue,
      points,
      tableRows: points.map((point) => point.item).reverse(),
      cameraDistribution,
      linePath,
      areaPath,
      labelIndexes,
      barWidth: Math.max(4, Math.min(18, plotWidth / Math.max(points.length, 1) * 0.48)),
      summary: {
        total,
        average: points.length ? total / points.length : 0,
        peak,
        latest: points.at(-1)?.value || 0,
      },
    };
  }, [records, recordLimit, metricKey]);

  return (
    <section className="analytics-page">
      <Panel
        title="检测数据趋势"
        icon={<BarChart3 size={18} />}
        action={
          <div className="trend-range-switch" role="group" aria-label="趋势记录范围">
            {TREND_LIMITS.map((limit) => (
              <button type="button" className={cx(recordLimit === limit && "active")} onClick={() => setRecordLimit(limit)} key={limit}>
                最近 {limit} 条
              </button>
            ))}
          </div>
        }
      >
        <div className="trend-toolbar">
          <div className="trend-metric-switch" role="group" aria-label="趋势指标">
            {Object.entries(TREND_METRICS).map(([key, item]) => (
              <button type="button" className={cx(metricKey === key && "active")} onClick={() => setMetricKey(key)} key={key}>
                {item.label}
              </button>
            ))}
          </div>
          <p>按检测时间排序，共加载 {chart.points.length} 条记录</p>
        </div>

        <div className="trend-summary-grid">
          <article><span>累计{metric.shortLabel}</span><strong>{chart.summary.total.toLocaleString("zh-CN")}</strong><small>当前范围总数量</small></article>
          <article><span>平均每次</span><strong>{chart.summary.average.toFixed(1)}</strong><small>单次检测平均值</small></article>
          <article><span>峰值</span><strong>{chart.summary.peak.toLocaleString("zh-CN")}</strong><small>范围内最高数量</small></article>
          <article><span>最新检测</span><strong>{chart.summary.latest.toLocaleString("zh-CN")}</strong><small>{formatTrendTime(chart.points.at(-1)?.item.created_at)}</small></article>
        </div>

        <div className="trend-chart-shell">
          {chart.points.length ? (
            <svg className="trend-chart" viewBox={`0 0 ${chart.width} ${chart.height}`} role="img" aria-label={`${metric.label}随检测时间变化趋势`}>
              {[0, 0.25, 0.5, 0.75, 1].map((ratio) => {
                const y = chart.padding.top + (chart.baseline - chart.padding.top) * ratio;
                const value = Math.round(chart.maxValue * (1 - ratio));
                return (
                  <g key={ratio}>
                    <line x1={chart.padding.left} y1={y} x2={chart.width - chart.padding.right} y2={y} className="trend-grid-line" />
                    <text x={chart.padding.left - 12} y={y + 4} textAnchor="end" className="trend-axis-label">{value}</text>
                  </g>
                );
              })}
              <path d={chart.areaPath} fill={metric.tint} className="trend-area" />
              {chart.points.map((point) => (
                <rect
                  key={`bar-${point.item.id}`}
                  x={point.x - chart.barWidth / 2}
                  y={point.y}
                  width={chart.barWidth}
                  height={Math.max(1, chart.baseline - point.y)}
                  fill={metric.color}
                  className="trend-bar"
                >
                  <title>{`${formatTrendTime(point.item.created_at)} · ${point.item.camera_id || "未知摄像头"} · ${metric.label} ${point.value}`}</title>
                </rect>
              ))}
              <path d={chart.linePath} fill="none" stroke={metric.color} className="trend-line" />
              {chart.points.length <= 50 && chart.points.map((point) => (
                <circle key={`point-${point.item.id}`} cx={point.x} cy={point.y} r="3.5" fill="#ffffff" stroke={metric.color} className="trend-point">
                  <title>{`${formatTrendTime(point.item.created_at)} · ${metric.label} ${point.value}`}</title>
                </circle>
              ))}
              {chart.labelIndexes.map((index) => {
                const point = chart.points[index];
                return <text key={`label-${point.item.id}`} x={point.x} y={chart.height - 18} textAnchor="middle" className="trend-axis-label">{formatTrendTime(point.item.created_at)}</text>;
              })}
            </svg>
          ) : (
            <div className="trend-empty"><BarChart3 size={30} /><strong>暂无检测趋势</strong><span>模型产生检测记录后，这里会自动显示数量和变化趋势。</span></div>
          )}
        </div>
        <div className="trend-legend"><i style={{ background: metric.color }} /><span>{metric.label}</span><em>柱形表示单次检测数量，折线表示变化趋势</em></div>

        <section className="trend-pie-section" aria-labelledby="cameraDistributionTitle">
          <header>
            <div>
              <strong id="cameraDistributionTitle">摄像头检测占比</strong>
              <span>按{metric.label}汇总</span>
            </div>
            <small>当前 {chart.points.length} 条检测记录</small>
          </header>
          {chart.cameraDistribution.length ? (
            <div className="trend-pie-content">
              <figure>
                <svg className="trend-pie-chart" viewBox="0 0 180 180" role="img" aria-label={`各摄像头${metric.label}占比`}>
                  <circle className="trend-pie-track" cx="90" cy="90" r="62" pathLength="100" />
                  {chart.cameraDistribution.map((item) => (
                    <circle
                      className="trend-pie-segment"
                      cx="90"
                      cy="90"
                      r="62"
                      pathLength="100"
                      fill="none"
                      stroke={item.color}
                      strokeDasharray={`${item.percentage} ${100 - item.percentage}`}
                      strokeDashoffset={-item.offset}
                      transform="rotate(-90 90 90)"
                      key={item.name}
                    >
                      <title>{`${item.name} · ${item.value} · ${item.percentage.toFixed(1)}%`}</title>
                    </circle>
                  ))}
                  <text x="90" y="85" textAnchor="middle" className="trend-pie-total">{chart.summary.total.toLocaleString("zh-CN")}</text>
                  <text x="90" y="106" textAnchor="middle" className="trend-pie-caption">{metric.shortLabel}总量</text>
                </svg>
              </figure>
              <div className="trend-pie-legend">
                {chart.cameraDistribution.map((item) => (
                  <div key={item.name}>
                    <i style={{ background: item.color }} />
                    <strong title={item.name}>{item.name}</strong>
                    <span>{item.value.toLocaleString("zh-CN")}</span>
                    <em>{item.percentage.toFixed(1)}%</em>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="trend-pie-empty"><BarChart3 size={26} /><span>当前范围内没有可用于占比分析的数据</span></div>
          )}
        </section>

        <section className="trend-table-section" aria-labelledby="trendTableTitle">
          <header>
            <div>
              <strong id="trendTableTitle">检测明细</strong>
              <span>当前范围共 {chart.tableRows.length} 条记录</span>
            </div>
            <small>最新记录优先</small>
          </header>
          <div className="trend-table-wrap">
            <table className="trend-table">
              <thead>
                <tr>
                  <th>检测时间</th>
                  <th>摄像头</th>
                  <th className={cx(metricKey === "vehicle_count" && "active-metric")}>车辆</th>
                  <th className={cx(metricKey === "detection_count" && "active-metric")}>检测框</th>
                  <th className={cx(metricKey === "event_count" && "active-metric")}>事件</th>
                  <th>拥堵状态</th>
                  <th>推理耗时</th>
                </tr>
              </thead>
              <tbody>
                {chart.tableRows.length ? chart.tableRows.map((item) => (
                  <tr key={item.id}>
                    <td>{formatTrendTime(item.created_at)}</td>
                    <td><strong>{item.camera_id || "--"}</strong></td>
                    <td className={cx(metricKey === "vehicle_count" && "active-metric")}>{Number(item.vehicle_count) || 0}</td>
                    <td className={cx(metricKey === "detection_count" && "active-metric")}>{Number(item.detection_count) || 0}</td>
                    <td className={cx(metricKey === "event_count" && "active-metric")}>{Number(item.event_count) || 0}</td>
                    <td><span className={cx("trend-congestion", item.congestion_level || "unknown")}>{congestionText(item.congestion_level)}</span></td>
                    <td>{item.inference_ms == null ? "--" : `${Math.round(Number(item.inference_ms) || 0)} ms`}</td>
                  </tr>
                )) : (
                  <tr><td colSpan="7" className="trend-table-empty">暂无检测记录</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </Panel>
    </section>
  );
}

function ResourceGauge({ icon, label, value, percent, hint, tone }) {
  const safePercent = Math.max(0, Math.min(100, Number(percent) || 0));
  return (
    <div className={cx("resource-gauge", tone)}>
      <span className="resource-icon">{icon}</span>
      <div className="resource-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <div className="resource-track" aria-label={`${label} ${safePercent}%`}>
          <i style={{ width: `${safePercent}%` }} />
        </div>
        <small>{hint}</small>
      </div>
    </div>
  );
}

function ResourceMonitor({ resources }) {
  const cpu = resources?.cpu || emptyResources.cpu;
  const memory = resources?.memory || emptyResources.memory;
  const gpu = resources?.gpu || emptyResources.gpu;
  const inferenceMs = resources?.inference?.latest_ms;
  const inferenceLoad = inferenceMs == null ? 0 : Math.min(100, (inferenceMs / 200) * 100);
  return (
    <section className="resource-monitor">
      <header>
        <span>
          <Activity size={17} />
          系统资源监控
        </span>
        <small>{gpu.available ? gpu.name : "未检测到独立显卡"} · 每 1.5 秒刷新</small>
      </header>
      <div className="resource-grid">
        <ResourceGauge
          icon={<Cpu size={18} />}
          label="CPU"
          value={`${Math.round(cpu.usage_percent || 0)}%`}
          percent={cpu.usage_percent}
          hint={`${cpu.physical_cores || "--"} 核 / ${cpu.logical_cores || "--"} 线程`}
          tone="cpu"
        />
        <ResourceGauge
          icon={<MemoryStick size={18} />}
          label="系统内存"
          value={`${memory.usage_percent || 0}%`}
          percent={memory.usage_percent}
          hint={`${memory.used_gb || 0} / ${memory.total_gb || 0} GB`}
          tone="memory"
        />
        <ResourceGauge
          icon={<Activity size={18} />}
          label="GPU"
          value={gpu.available ? `${Math.round(gpu.usage_percent || 0)}%` : "--"}
          percent={gpu.usage_percent}
          hint={gpu.available ? `${gpu.temperature_c ?? "--"}°C` : "不可用"}
          tone="gpu"
        />
        <ResourceGauge
          icon={<Database size={18} />}
          label="显存"
          value={gpu.available ? `${gpu.memory_usage_percent || 0}%` : "--"}
          percent={gpu.memory_usage_percent}
          hint={gpu.available ? `${gpu.memory_used_gb || 0} / ${gpu.memory_total_gb || 0} GB` : "不可用"}
          tone="vram"
        />
        <ResourceGauge
          icon={<Clock3 size={18} />}
          label="推理耗时"
          value={inferenceMs == null ? "--" : `${Math.round(inferenceMs)} ms`}
          percent={inferenceLoad}
          hint={inferenceMs == null ? "等待模型结果" : inferenceMs <= 100 ? "实时性能良好" : "模型负载较高"}
          tone="inference"
        />
      </div>
    </section>
  );
}

function WeatherPanel({ weather }) {
  const data = weather || emptyWeather;
  const visibility = data.visibility_m == null ? "--" : `${(data.visibility_m / 1000).toFixed(1)} km`;
  return (
    <Panel title="北京天气与出行建议" icon={<CloudSun size={18} />} className="weather-panel">
      <div className="weather-summary">
        <div>
          <strong>{data.city || "北京"} · {data.condition || "天气变化"}</strong>
          <span>{data.available ? `${data.temperature_c}°C · 体感 ${data.feels_like_c}°C` : "天气服务暂不可用"}</span>
        </div>
        <em className={cx("weather-level", data.advice_level)}>{data.advice_level === "critical" ? "谨慎出行" : data.advice_level === "warning" ? "注意路况" : "适宜出行"}</em>
      </div>
      {data.available && (
        <div className="weather-data">
          <span>湿度 {data.humidity_percent}%</span>
          <span>降水 {data.precipitation_mm} mm</span>
          <span>风速 {data.wind_speed_kmh} km/h</span>
          <span>能见度 {visibility}</span>
        </div>
      )}
      <div className="weather-advice">
        <p><b>驾驶</b>{data.driving_advice}</p>
        <p><b>出行</b>{data.travel_advice}</p>
      </div>
    </Panel>
  );
}

function CameraCard({ camera, status, selected, onSelect, onStart, onStop }) {
  const online = status?.connected;
  return (
    <article className={cx("camera-card", selected && "selected", online && "online")}>
      <button type="button" className="camera-main" onClick={onSelect}>
        <span className="camera-icon">
          <Camera size={16} />
        </span>
        <span>
          <strong>{camera.name}</strong>
          <small>{camera.location}</small>
        </span>
        <em title={status?.last_error || statusText(status)}>{statusText(status)}</em>
      </button>
      <div className="camera-actions">
        <button type="button" onClick={onStart}>
          <Play size={13} />
          启动
        </button>
        <button type="button" onClick={onStop}>
          <Square size={13} />
          停止
        </button>
      </div>
    </article>
  );
}

function HeatmapView({ analysis, roadModel, roadHeatmap, cameraId, globalView = false }) {
  const world = roadModel?.world || roadHeatmap?.world || { width: 1200, height: 760 };
  const lanes = roadModel?.lanes || [];
  const nodes = roadModel?.nodes || [];
  const intersections = roadModel?.intersections || [];
  const buildings = roadModel?.buildings || [];
  const cameraState = roadModel?.cameras?.[cameraId];
  const cameraViews = roadModel?.camera_views?.[cameraId] || [];
  const activeCamera = cameraViews[0];
  const viewport = globalView
    ? { x: 0, y: 0, width: world.width, height: world.height }
    : cameraState?.local_viewbox || { x: 0, y: 0, width: world.width, height: world.height };
  const intersectsViewport = (x, y, width = 0, height = 0) => (
    x + width >= viewport.x
    && x <= viewport.x + viewport.width
    && y + height >= viewport.y
    && y <= viewport.y + viewport.height
  );
  const pathIntersectsViewport = (path = []) => {
    if (!path.length) return false;
    let minX = Number(path[0].x);
    let maxX = minX;
    let minY = Number(path[0].y);
    let maxY = minY;
    for (const point of path) {
      const x = Number(point.x);
      const y = Number(point.y);
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }
    return intersectsViewport(minX, minY, maxX - minX, maxY - minY);
  };
  const polygonIntersectsViewport = (polygon = []) => pathIntersectsViewport(polygon);
  const laneStats = roadHeatmap?.lane_stats || {};
  const junctionStats = roadHeatmap?.junction_stats || {};
  const visibleBuildings = globalView
    ? buildings
    : buildings.filter((building) => intersectsViewport(building.x, building.y, building.width, building.height));
  const visibleLanes = globalView
    ? lanes
    : lanes.filter((lane) => pathIntersectsViewport(lane.path || []));
  const visibleIntersections = globalView
    ? intersections
    : intersections.filter((zone) => polygonIntersectsViewport(zone.polygon || []));
  const visibleNodes = globalView
    ? nodes
    : nodes.filter((node) => intersectsViewport(node.x, node.y));
  const visibleCameraViews = globalView
    ? Object.values(roadModel?.camera_views || {}).flat()
    : cameraViews;
  const fovPolygon = (camera) => {
    const angle = ((Number(camera.direction || 0) - 90) * Math.PI) / 180;
    const halfAngle = ((Number(camera.fov || 30) / 2) * Math.PI) / 180;
    const range = Math.min(Number(camera.range || 180), 250);
    const pointAt = (offset) => ({
      x: Number(camera.x) + Math.cos(angle + offset) * range,
      y: Number(camera.y) + Math.sin(angle + offset) * range,
    });
    const left = pointAt(-halfAngle);
    const right = pointAt(halfAngle);
    return `${camera.x},${camera.y} ${left.x},${left.y} ${right.x},${right.y}`;
  };
  return (
    <div className={cx("heatmap", "modeled-heatmap", globalView ? "global-roadmap" : "local-roadmap")}>
      <svg viewBox={`${viewport.x} ${viewport.y} ${viewport.width} ${viewport.height}`} role="img" aria-label={globalView ? "沙盘全局道路热力图" : "当前摄像头局部道路热力图"}>
        <defs>
          <pattern id={globalView ? "road-grid-global" : "road-grid-local"} width="20" height="20" patternUnits="userSpaceOnUse">
            <path d="M 20 0 L 0 0 0 20" className="map-grid-line" />
          </pattern>
          <marker id={globalView ? "lane-arrow-global" : "lane-arrow-local"} markerWidth="7" markerHeight="7" refX="4" refY="3.5" orient="auto" markerUnits="strokeWidth">
            <path d="M 0 0 L 7 3.5 L 0 7 z" className="map-arrow" />
          </marker>
        </defs>
        <rect x={viewport.x} y={viewport.y} width={viewport.width} height={viewport.height} className="map-ground" />
        <rect x={viewport.x} y={viewport.y} width={viewport.width} height={viewport.height} fill={`url(#${globalView ? "road-grid-global" : "road-grid-local"})`} />
        {visibleBuildings.map((building) => (
          <rect
            key={building.id}
            x={building.x}
            y={building.y}
            width={building.width}
            height={building.height}
            className="map-building"
          />
        ))}
        {visibleLanes.map((lane) => (
          <g key={lane.id}>
            <polyline
              points={(lane.path || []).map((point) => `${point.x},${point.y}`).join(" ")}
              strokeWidth={(lane.width || 28) + 6}
              className="map-road-surface"
            />
            {laneStats[lane.id] && (
              <polyline
                points={(lane.path || []).map((point) => `${point.x},${point.y}`).join(" ")}
                strokeWidth={(lane.width || 28) + 1}
                className={cx("map-road-flow", laneStats[lane.id].level)}
              />
            )}
          </g>
        ))}
        {visibleIntersections.map((zone) => (
          <polygon
            key={zone.id}
            points={(zone.polygon || []).map((point) => `${point.x},${point.y}`).join(" ")}
            className={cx("map-junction-zone", junctionStats[zone.id]?.level)}
          />
        ))}
        {visibleLanes.map((lane) => (
          <polyline
            key={`${lane.id}-direction`}
            points={(lane.path || []).map((point) => `${point.x},${point.y}`).join(" ")}
            strokeWidth={1.5}
            markerEnd={`url(#${globalView ? "lane-arrow-global" : "lane-arrow-local"})`}
            className="map-lane"
          />
        ))}
        {visibleNodes.filter((node) => node.type === "junction").map((node) => (
          <circle key={node.id} cx={node.x} cy={node.y} r={globalView ? 8 : 5} className="map-node" />
        ))}
        {visibleCameraViews.map((camera, index) => (
          <g key={`${camera.id}-${index}`} className={cx("map-camera", camera.id === activeCamera?.id && "selected")}>
            <polygon points={fovPolygon(camera)} className="map-camera-fov" />
            <circle cx={camera.x} cy={camera.y} r={globalView ? 7 : 5} className="map-camera-dot" />
            {globalView && <text x={Number(camera.x) + 10} y={Number(camera.y) - 8}>{camera.place || camera.name}</text>}
          </g>
        ))}
      </svg>
      <div className="map-legend">
        <span className="view-label">{globalView ? "全局路网" : "当前视角"}</span>
        <span><i className="lane" />行车道</span>
        <span><i className="junction" />路口区域</span>
        {globalView && <span><i className="camera" />摄像头视域</span>}
        <span><i className="free" />畅通</span>
        <span><i className="slow" />缓行</span>
        <span><i className="congested" />拥堵</span>
      </div>
      {cameraState?.ready === false && <p>当前摄像头仅有 {cameraState.point_count} 个标定点，暂不生成世界坐标热力图。</p>}
      {cameraState?.ready !== false && !Object.keys(laneStats).length && <p>等待车辆轨迹投影到道路模型</p>}
    </div>
  );
}

function PreviewSlot({ slotIndex, cameraId, cameras, statuses, streamVersion, onChange, onSelect }) {
  const camera = cameras.find((item) => item.camera_id === cameraId) || cameras[0];
  const status = camera ? statuses[camera.camera_id] : null;

  return (
    <article className="preview-tile">
      <div className="preview-head">
        <strong>画面 {slotIndex + 1}</strong>
        <select value={camera?.camera_id || ""} onChange={(event) => onChange(slotIndex, event.target.value)}>
          {cameras.map((item) => (
            <option value={item.camera_id} key={item.camera_id}>
              {item.name}
            </option>
          ))}
        </select>
      </div>
      <button type="button" className="preview-screen" onClick={() => camera && onSelect(camera.camera_id)}>
        {camera && status?.running ? (
          <img src={`${API_BASE}/api/cameras/${camera.camera_id}/mjpeg?v=${streamVersion}`} alt={`${camera.name} 预览`} />
        ) : (
          <span>{camera ? "未启动" : "无摄像头"}</span>
        )}
      </button>
      <footer>
        <span>{camera?.name || "--"}</span>
        <em>{statusText(status)}</em>
      </footer>
    </article>
  );
}

function App() {
  const [cameras, setCameras] = useState([]);
  const [statuses, setStatuses] = useState({});
  const [selectedCameraId, setSelectedCameraId] = useState("live1");
  const [previewSlots, setPreviewSlots] = useState(["live1", "live2", "live3", "live4"]);
  const [analysis, setAnalysis] = useState(emptyAnalysis);
  const [dashboard, setDashboard] = useState(null);
  const [history, setHistory] = useState([]);
  const [whitelist, setWhitelist] = useState([]);
  const [whitelistPlate, setWhitelistPlate] = useState("");
  const [whitelistOwner, setWhitelistOwner] = useState("沙盘白名单车辆");
  const [whitelistNote, setWhitelistNote] = useState("准入车牌");
  const [whitelistSearchText, setWhitelistSearchText] = useState("");
  const [whitelistQuery, setWhitelistQuery] = useState("");
  const [whitelistMessage, setWhitelistMessage] = useState("");
  const [viewMode, setViewMode] = useState("monitor");
  const [heatmapOpen, setHeatmapOpen] = useState(false);
  const [phoneUrl, setPhoneUrl] = useState(DEFAULT_PHONE_URL);
  const [selectedModelName, setSelectedModelName] = useState("auto");
  const [modelConfig, setModelConfig] = useState({
    confidence: 0.35,
    iou: 0.45,
    detection_interval_ms: 500,
    inference_size: 640,
    enabled_tasks: ["vehicle", "tracking", "plate", "obstacle", "traffic"],
  });
  const [modelConfigDirty, setModelConfigDirty] = useState(false);
  const [modelMessage, setModelMessage] = useState("");
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("strans_token") || "");
  const [currentUser, setCurrentUser] = useState(null);
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({ username: "admin", password: "admin123", captcha_code: "" });
  const [captcha, setCaptcha] = useState({ captcha_id: "", image: "" });
  const [authMessage, setAuthMessage] = useState("");
  const [logs, setLogs] = useState(["系统已就绪，请启动摄像头或接入手机视频源"]);
  const [streamVersion, setStreamVersion] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [resources, setResources] = useState(emptyResources);
  const [weather, setWeather] = useState(emptyWeather);
  const [roadModel, setRoadModel] = useState(null);
  const [roadHeatmap, setRoadHeatmap] = useState({ points: [] });
  const [analysisMode, setAnalysisMode] = useState("traffic");
  const [reports, setReports] = useState([]);
  const [activeReportId, setActiveReportId] = useState(null);
  const [reportConfig, setReportConfig] = useState({ api_base: "https://api.deepseek.com/v1", model: "deepseek-chat", api_key: "", configured: false, api_key_masked: "" });
  const [reportMessage, setReportMessage] = useState("");
  const [voiceListening, setVoiceListening] = useState(false);
  const [voiceMessage, setVoiceMessage] = useState("点击开始识别，展开下方指令表查看全部可用说法");
  const [systemUsers, setSystemUsers] = useState([]);
  const [incidents, setIncidents] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [featureMessage, setFeatureMessage] = useState("");
  const [passwordForm, setPasswordForm] = useState({ old_password: "", new_password: "" });
  const [cameraForm, setCameraForm] = useState({ camera_id: "", name: "", type: "custom", stream_url: "", location: "", description: "" });
  const [incidentNotes, setIncidentNotes] = useState({});
  const [resetPasswords, setResetPasswords] = useState({});
  const [schedulerState, setSchedulerState] = useState({ enabled: true, active: [], decisions: [] });

  const selectedCamera = cameras.find((item) => item.camera_id === selectedCameraId) || cameras[0];
  const selectedStatus = selectedCamera ? statuses[selectedCamera.camera_id] : null;
  const stats = analysis.traffic_stats || emptyAnalysis.traffic_stats;
  const streamUrl = useMemo(
    () => (selectedCamera ? `${API_BASE}/api/cameras/${selectedCamera.camera_id}/model-mjpeg?model_name=${selectedModelName}&task_mode=${analysisMode}&v=${streamVersion}` : ""),
    [selectedCamera, selectedModelName, analysisMode, streamVersion],
  );

  function addLog(message) {
    const time = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    setLogs((prev) => [`${time}  ${message}`, ...prev].slice(0, 16));
  }

  async function requestJson(path, options) {
    const headers = {
      ...(options?.headers || {}),
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    };
    const response = await fetchWithTimeout(`${API_BASE}${path}`, { ...options, headers });
    if (response.status === 401) {
      localStorage.removeItem("strans_token");
      setAuthToken("");
      setCurrentUser(null);
    }
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `${response.status} ${path}`);
    }
    return response.json();
  }

  const loadCaptcha = useCallback(async () => {
    try {
      const response = await fetchWithTimeout(`${API_BASE}/api/auth/captcha`);
      if (!response.ok) throw new Error(String(response.status));
      const data = await response.json();
      setCaptcha(data);
      setAuthForm((prev) => ({ ...prev, captcha_code: "" }));
    } catch (error) {
      setAuthMessage(`验证码加载失败：${error.message}`);
    }
  }, []);

  useEffect(() => {
    loadCaptcha();
  }, [loadCaptcha]);

  useEffect(() => {
    if (!authToken) return;
    requestJson("/api/auth/me")
      .then((user) => setCurrentUser(user))
      .catch(() => {
        localStorage.removeItem("strans_token");
        setAuthToken("");
        setCurrentUser(null);
      });
  }, [authToken]);

  useEffect(() => {
    if (!authToken || !currentUser) return;
    fetch(`${API_BASE}/api/road-model`, { headers: { Authorization: `Bearer ${authToken}` } })
      .then((response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then(setRoadModel)
      .catch((error) => addLog(`道路模型加载失败：${error.message}`));
  }, [authToken, currentUser?.id]);

  useEffect(() => {
    if (!authToken || !currentUser || viewMode !== "reports") return;
    requestJson("/api/intelligence/reports?limit=30")
      .then((data) => {
        const items = data.items || [];
        setReports(items);
        setActiveReportId((previous) => previous || items[0]?.id || null);
      })
      .catch((error) => setReportMessage(`报告列表加载失败：${error.message}`));
    if (currentUser.role === "admin") {
      requestJson("/api/intelligence/config")
        .then((data) => setReportConfig((previous) => ({ ...previous, ...data, api_key: "" })))
        .catch((error) => setReportMessage(`DeepSeek 配置加载失败：${error.message}`));
    }
  }, [authToken, currentUser, viewMode]);

  const loadFeatureData = useCallback(async () => {
    if (!authToken || !currentUser || !FEATURE_VIEWS.has(viewMode)) return;
    try {
      if (viewMode === "history" || viewMode === "analytics") {
        const data = await requestJson("/api/history?limit=100");
        setHistory(data.items || []);
      } else if (viewMode === "incidents") {
        const data = await requestJson("/api/incidents?limit=100");
        setIncidents(data.items || []);
      } else if (viewMode === "users" && currentUser.role === "admin") {
        const data = await requestJson("/api/admin/users");
        setSystemUsers(data.items || []);
      } else if (viewMode === "audit" && currentUser.role === "admin") {
        const data = await requestJson("/api/admin/audit?limit=150");
        setAuditLogs(data.items || []);
      } else if (viewMode === "cameras") {
        const data = await requestJson("/api/cameras");
        setCameras(data || []);
      } else if (viewMode === "scheduler") {
        setSchedulerState(await requestJson("/api/model-scheduler"));
      }
    } catch (error) {
      setFeatureMessage(`功能数据加载失败：${error.message}`);
    }
  }, [authToken, currentUser, viewMode]);

  useEffect(() => {
    loadFeatureData();
  }, [loadFeatureData]);

  useEffect(() => {
    if (viewMode !== "scheduler" || !authToken || !currentUser) return undefined;
    const timer = window.setInterval(() => {
      requestJson("/api/model-scheduler").then(setSchedulerState).catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [viewMode, authToken, currentUser?.id]);

  const refresh = useCallback(async () => {
    if (!authToken || !currentUser) return;
    try {
      const [cameraList, statusList, latest, dash, historyData, whitelistData, resourceData, weatherData, heatmapData] = await Promise.all([
        requestJson("/api/cameras"),
        requestJson("/api/cameras/status"),
        requestJson("/api/analysis/latest"),
        requestJson("/api/dashboard"),
        requestJson("/api/history?limit=8"),
        requestJson("/api/whitelist"),
        requestJson("/api/system/resources"),
        requestJson("/api/weather/beijing"),
        requestJson(`/api/road-model/heatmap?camera_id=${encodeURIComponent(selectedCameraId)}`),
      ]);
      setCameras(cameraList);
      setStatuses(Object.fromEntries((statusList.items || []).map((item) => [item.camera_id, item.status])));
      setAnalysis(latest || emptyAnalysis);
      setDashboard(dash);
      if (viewMode !== "history" && viewMode !== "analytics") setHistory(historyData.items || []);
      setWhitelist(whitelistData.items || []);
      setResources(resourceData || emptyResources);
      setWeather(weatherData || emptyWeather);
      setRoadHeatmap(heatmapData || { points: [] });
      if (!modelConfigDirty && dash?.config) setModelConfig(dash.config);
      if (!selectedCameraId && cameraList[0]) setSelectedCameraId(cameraList[0].camera_id);
      setPreviewSlots((prev) => prev.map((id, index) => (cameraList.some((item) => item.camera_id === id) ? id : cameraList[index]?.camera_id || "")));
    } catch (error) {
      addLog(`后端连接失败：${error.message}`);
    }
  }, [selectedCameraId, authToken, currentUser, viewMode]);

  usePolling(refresh, 1500);

  async function submitAuth(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const result = await fetchWithTimeout(`${API_BASE}/api/auth/${authMode === "login" ? "login" : "register"}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: authForm.username.trim(),
          password: authForm.password,
          captcha_id: captcha.captcha_id,
          captcha_code: authForm.captcha_code,
        }),
      });
      const data = await result.json();
      if (!result.ok) throw new Error(data.detail || "认证失败");
      localStorage.setItem("strans_token", data.token);
      setAuthToken(data.token);
      setCurrentUser(data.user);
      setAuthMessage("");
      await refresh();
    } catch (error) {
      setAuthMessage(error.message);
      await loadCaptcha();
    } finally {
      setBusy(false);
    }
  }

  async function logout() {
    try {
      await requestJson("/api/auth/logout", { method: "POST" });
    } catch {
      // Local logout still succeeds if the server is already gone.
    }
    localStorage.removeItem("strans_token");
    setAuthToken("");
    setCurrentUser(null);
    setViewMode("monitor");
    await loadCaptcha();
  }

  function changePreviewSlot(index, cameraId) {
    setPreviewSlots((prev) => prev.map((item, current) => (current === index ? cameraId : item)));
  }

  async function startCamera(cameraId) {
    setBusy(true);
    try {
      await requestJson(`/api/cameras/${cameraId}/start`, { method: "POST" });
      setSelectedCameraId(cameraId);
      setStreamVersion(Date.now());
      addLog(`启动摄像头：${cameraId}`);
      await refresh();
    } catch (error) {
      addLog(`摄像头启动失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function stopCamera(cameraId) {
    setBusy(true);
    try {
      await requestJson(`/api/cameras/${cameraId}/stop`, { method: "POST" });
      addLog(`停止摄像头：${cameraId}`);
      await refresh();
    } catch (error) {
      addLog(`摄像头停止失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function connectPhone() {
    if (!phoneUrl.trim()) return;
    setBusy(true);
    try {
      const camera = await requestJson("/api/video/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: phoneUrl.trim(), name: "手机视频源", location: "手动接入" }),
      });
      setSelectedCameraId(camera.camera_id);
      setStreamVersion(Date.now());
      addLog(`接入手机视频：${phoneUrl}`);
      await refresh();
    } catch (error) {
      addLog(`手机视频接入失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function inferOnce() {
    if (!selectedCamera) return;
    setBusy(true);
    try {
      const path = analysisMode === "road_anomaly"
        ? `/api/road-anomaly/analyze/${selectedCamera.camera_id}?include_damage_model=true`
        : `/api/algorithm/infer/${selectedCamera.camera_id}`;
      const result = await requestJson(path, { method: "POST" });
      setAnalysis(result);
      addLog(`${analysisMode === "road_anomaly" ? "道路异常" : "车辆监控"}分析完成：${selectedCamera.name}`);
      await refresh();
    } catch (error) {
      addLog(`模型检测请求失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function saveModelConfig() {
    setBusy(true);
    try {
      await requestJson("/api/config/threshold", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(modelConfig),
      });
      setModelConfigDirty(false);
      setModelMessage("模型参数已保存，实时画面刷新后生效。");
      setStreamVersion(Date.now());
      await refresh();
    } catch (error) {
      setModelMessage(`模型参数保存失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function analyzeRoadAnomaly() {
    if (!selectedCamera) return;
    setBusy(true);
    try {
      const result = await requestJson(`/api/road-anomaly/analyze/${selectedCamera.camera_id}?include_damage_model=true`, { method: "POST" });
      setAnalysis(result);
      addLog(`道路异常分析完成：${selectedCamera.name}`);
      await refresh();
    } catch (error) {
      addLog(`道路异常分析失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  function updateModelConfig(key, value) {
    setModelConfig((prev) => ({ ...prev, [key]: value }));
    setModelConfigDirty(true);
  }

  function switchAnalysisMode(mode) {
    if (mode === analysisMode) return;
    setAnalysisMode(mode);
    setAnalysis(emptyAnalysis);
    setStreamVersion(Date.now());
    addLog(mode === "road_anomaly" ? "已切换至道路异常识别：车辆统计与热力图暂停。" : "已切换至车辆监控：恢复车辆、车牌与热力分析。 ");
  }

  function announceVoiceResult(message) {
    setVoiceMessage(message);
    addLog(`语音控制：${message}`);
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(message));
    }
  }

  function getVoiceCamera(command) {
    const match = command.match(/(?:第)?([一二三四五六七八九十\d]+)(?:号)?摄像头/);
    if (!match) return null;
    const digitMap = { 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9, 十: 10 };
    const cameraNumber = Number(match[1]) || digitMap[match[1]];
    return cameras.find((item) => item.camera_id === `live${cameraNumber}` || item.camera_id === `cam_${cameraNumber}` || item.name.includes(`${cameraNumber}号`)) || null;
  }

  function countTodayWhitelistPasses() {
    const now = new Date();
    const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
    const normalizePlate = (plate) => String(plate || "").toUpperCase().replace(/[^\u4E00-\u9FFFA-Z0-9]/g, "");
    const whitelistPlates = new Set(whitelist.filter((item) => item.enabled !== false).map((item) => normalizePlate(item.plate_no)));
    const passedPlates = new Set();
    history
      .filter((item) => String(item.created_at || item.timestamp || "").slice(0, 10) === today)
      .forEach((item) => {
        String(item.plates || "")
          .split(/[\s,，、|/]+/)
          .map(normalizePlate)
          .filter((plate) => whitelistPlates.has(plate))
          .forEach((plate) => passedPlates.add(plate));
      });
    return passedPlates.size;
  }

  function runVoiceCommand(transcript) {
    const command = String(transcript || "").replace(/[，,。.!！]/g, "").replace(/\s/g, "");
    if (!command) return;

    if (/打开.*道路异常|切换.*道路异常|道路异常模式/.test(command)) {
      switchAnalysisMode("road_anomaly");
      announceVoiceResult("已打开道路异常模式");
      return;
    }
    if (/打开.*车辆监控|切换.*车辆监控|车辆监控模式/.test(command)) {
      switchAnalysisMode("traffic");
      announceVoiceResult("已切换到车辆监控模式");
      return;
    }
    if (/查看.*历史|打开.*历史/.test(command)) {
      setViewMode("history");
      announceVoiceResult("已打开历史记录");
      return;
    }
    if (/查看.*报告|打开.*报告|智能报告/.test(command)) {
      setViewMode("reports");
      announceVoiceResult("已打开智能报告");
      return;
    }
    if (/打开.*白名单|查看.*白名单/.test(command)) {
      if (!isAdmin) {
        announceVoiceResult("白名单配置需要管理员权限");
      } else {
        setViewMode("whitelist");
        announceVoiceResult("已打开白名单配置");
      }
      return;
    }
    if (/打开.*模型配置|查看.*模型配置/.test(command)) {
      if (!isAdmin) {
        announceVoiceResult("模型配置需要管理员权限");
      } else {
        setViewMode("models");
        announceVoiceResult("已打开模型配置");
      }
      return;
    }
    if (/返回.*监控|打开.*实时监控|实时监控首页/.test(command)) {
      setViewMode("monitor");
      announceVoiceResult("已返回实时监控");
      return;
    }
    if (/打开.*热力图|查看.*热力图/.test(command)) {
      if (analysisMode !== "traffic") {
        announceVoiceResult("道路异常模式不显示拥堵热力图，请先切换到车辆监控模式");
      } else {
        setHeatmapOpen(true);
        announceVoiceResult("已打开全局道路拥堵图");
      }
      return;
    }
    if (/关闭.*热力图/.test(command)) {
      setHeatmapOpen(false);
      announceVoiceResult("已关闭全局道路拥堵图");
      return;
    }
    if (/分析.*当前帧|检测.*当前帧|开始分析/.test(command)) {
      if (!selectedCamera) {
        announceVoiceResult("请先选择摄像头");
      } else {
        inferOnce();
        announceVoiceResult("正在分析当前画面");
      }
      return;
    }
    if (/刷新.*画面|刷新.*视频|重新加载画面/.test(command)) {
      setStreamVersion(Date.now());
      announceVoiceResult("已刷新实时画面");
      return;
    }
    if (/停止.*当前摄像头|关闭.*当前摄像头/.test(command)) {
      if (!selectedCamera) {
        announceVoiceResult("当前没有可停止的摄像头");
      } else {
        stopCamera(selectedCamera.camera_id);
        announceVoiceResult(`正在停止${selectedCamera.name}`);
      }
      return;
    }

    const camera = getVoiceCamera(command);
    if (camera) {
      if (/启动|打开/.test(command)) {
        startCamera(camera.camera_id);
        announceVoiceResult(`正在启动${camera.name}`);
      } else if (/停止|关闭/.test(command)) {
        stopCamera(camera.camera_id);
        announceVoiceResult(`正在停止${camera.name}`);
      } else {
        setSelectedCameraId(camera.camera_id);
        setStreamVersion(Date.now());
        announceVoiceResult(`已切换到${camera.name}`);
      }
      return;
    }
    if (/查询.*今天.*白名单.*通过|今天.*白名单.*通过.*几辆/.test(command)) {
      announceVoiceResult(`今天已识别白名单通过车辆${countTodayWhitelistPasses()}辆`);
      return;
    }

    announceVoiceResult("暂不支持这条语音指令，请展开指令表查看可用说法");
  }

  function startVoiceRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setVoiceMessage("当前浏览器不支持 Web Speech API，请使用新版 Edge 或 Chrome。");
      return;
    }
    if (voiceListening) return;
    const recognition = new SpeechRecognition();
    recognition.lang = "zh-CN";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.onstart = () => {
      setVoiceListening(true);
      setVoiceMessage("正在聆听，请说出指令");
    };
    recognition.onresult = (event) => {
      setVoiceListening(false);
      runVoiceCommand(event.results?.[0]?.[0]?.transcript || "");
    };
    recognition.onerror = (event) => {
      setVoiceListening(false);
      setVoiceMessage(event.error === "not-allowed" ? "麦克风权限未开启，请在浏览器地址栏允许麦克风。" : `语音识别失败：${event.error}`);
    };
    recognition.onend = () => setVoiceListening(false);
    recognition.start();
  }

  async function addWhitelistPlate() {
    if (!whitelistPlate.trim()) return;
    setBusy(true);
    try {
      await requestJson("/api/whitelist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plate_no: whitelistPlate.trim(),
          owner: whitelistOwner.trim() || "沙盘白名单车辆",
          note: whitelistNote.trim() || "准入车牌",
        }),
      });
      addLog(`新增白名单车牌：${whitelistPlate.trim()}`);
      setWhitelistMessage(`已保存白名单车牌：${whitelistPlate.trim()}`);
      setWhitelistPlate("");
      setWhitelistOwner("沙盘白名单车辆");
      setWhitelistNote("准入车牌");
      await refresh();
    } catch (error) {
      addLog(`白名单保存失败：${error.message}`);
      setWhitelistMessage(`保存失败：${error.message}。如果后端未重启，请先重启后端服务。`);
    } finally {
      setBusy(false);
    }
  }

  async function removeWhitelistPlate(plateNo) {
    setBusy(true);
    try {
      await requestJson(`/api/whitelist/${encodeURIComponent(plateNo)}`, { method: "DELETE" });
      addLog(`移除白名单车牌：${plateNo}`);
      setWhitelistMessage(`已删除白名单车牌：${plateNo}`);
      await refresh();
    } catch (error) {
      addLog(`白名单删除失败：${error.message}`);
      setWhitelistMessage(`删除失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function changeOwnPassword(event) {
    event.preventDefault();
    setBusy(true);
    try {
      await requestJson("/api/auth/password", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(passwordForm),
      });
      setFeatureMessage("密码修改成功，请重新登录。");
      setPasswordForm({ old_password: "", new_password: "" });
      window.setTimeout(logout, 800);
    } catch (error) {
      setFeatureMessage(`密码修改失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function updateSystemUser(userId, updates) {
    setBusy(true);
    try {
      await requestJson(`/api/admin/users/${userId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
      setFeatureMessage("用户状态已更新。");
      await loadFeatureData();
    } catch (error) {
      setFeatureMessage(`用户更新失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function resetSystemUserPassword(userId) {
    const newPassword = resetPasswords[userId] || "";
    if (newPassword.length < 6) {
      setFeatureMessage("重置密码至少需要 6 位。");
      return;
    }
    setBusy(true);
    try {
      await requestJson(`/api/admin/users/${userId}/password`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: newPassword }),
      });
      setResetPasswords((previous) => ({ ...previous, [userId]: "" }));
      setFeatureMessage("密码已重置，该用户需要重新登录。");
    } catch (error) {
      setFeatureMessage(`密码重置失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteSystemUser(userId) {
    if (!window.confirm("确定删除这个普通用户吗？")) return;
    setBusy(true);
    try {
      await requestJson(`/api/admin/users/${userId}`, { method: "DELETE" });
      setFeatureMessage("用户已删除。");
      await loadFeatureData();
    } catch (error) {
      setFeatureMessage(`用户删除失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  function editManagedCamera(camera) {
    setCameraForm({
      camera_id: camera.camera_id,
      name: camera.name,
      type: camera.type,
      stream_url: camera.stream_url,
      location: camera.location,
      description: camera.description || "",
    });
  }

  function clearCameraForm() {
    setCameraForm({ camera_id: "", name: "", type: "custom", stream_url: "", location: "", description: "" });
  }

  async function saveManagedCamera(event) {
    event.preventDefault();
    setBusy(true);
    try {
      const editing = Boolean(cameraForm.camera_id);
      await requestJson(editing ? `/api/cameras/${cameraForm.camera_id}` : "/api/cameras", {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: cameraForm.name,
          type: cameraForm.type,
          stream_url: cameraForm.stream_url,
          location: cameraForm.location,
          description: cameraForm.description || null,
        }),
      });
      setFeatureMessage(editing ? "摄像头配置已更新。" : "摄像头已添加并写入数据库。");
      clearCameraForm();
      await loadFeatureData();
    } catch (error) {
      setFeatureMessage(`摄像头保存失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function testManagedCamera(cameraId) {
    setBusy(true);
    try {
      const result = await requestJson(`/api/cameras/${cameraId}/test`, { method: "POST" });
      setFeatureMessage(`${cameraId}：${result.message}${result.frame_width ? `，${result.frame_width}×${result.frame_height}` : ""}`);
    } catch (error) {
      setFeatureMessage(`连接测试失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteManagedCamera(cameraId) {
    if (!window.confirm("确定删除这个自定义摄像头吗？")) return;
    setBusy(true);
    try {
      await requestJson(`/api/cameras/${cameraId}`, { method: "DELETE" });
      setFeatureMessage("摄像头已删除。");
      if (cameraForm.camera_id === cameraId) clearCameraForm();
      await loadFeatureData();
    } catch (error) {
      setFeatureMessage(`摄像头删除失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function handleIncident(eventId, status) {
    setBusy(true);
    try {
      await requestJson(`/api/incidents/${encodeURIComponent(eventId)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status, note: incidentNotes[eventId] || "" }),
      });
      setFeatureMessage("告警处置状态已保存。");
      await loadFeatureData();
    } catch (error) {
      setFeatureMessage(`告警处置失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function downloadEvidencePackage(eventId) {
    try {
      const response = await fetchWithTimeout(`${API_BASE}/api/incidents/${encodeURIComponent(eventId)}/evidence`, {
        headers: { Authorization: `Bearer ${authToken}` },
      }, 15000);
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || `HTTP ${response.status}`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `evidence-${eventId}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
      setFeatureMessage("告警证据包已导出，包含原始帧、检测结果、处置记录和校验信息。");
    } catch (error) {
      setFeatureMessage(`证据包导出失败：${error.message}`);
    }
  }

  async function toggleAdaptiveScheduler() {
    setBusy(true);
    try {
      const next = !schedulerState.enabled;
      const data = await requestJson(`/api/model-scheduler?enabled=${next}`, { method: "PUT" });
      setSchedulerState(data);
      setFeatureMessage(next ? "自适应模型调度已启用。" : "已切换为人工固定参数。");
    } catch (error) {
      setFeatureMessage(`调度配置失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteHistoryRecord(recordId) {
    if (!window.confirm("确定删除这条历史记录吗？")) return;
    try {
      await requestJson(`/api/history/${recordId}`, { method: "DELETE" });
      setHistory((previous) => previous.filter((item) => item.id !== recordId));
      setFeatureMessage("历史记录已删除。");
    } catch (error) {
      setFeatureMessage(`历史记录删除失败：${error.message}`);
    }
  }

  async function downloadHistory(format) {
    try {
      const response = await fetchWithTimeout(`${API_BASE}/api/history/export?format=${format}`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) throw new Error(String(response.status));
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `traffic-analysis-history.${format}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setFeatureMessage(`导出失败：${error.message}`);
    }
  }

  async function saveReportConfig() {
    setBusy(true);
    try {
      const data = await requestJson("/api/intelligence/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          api_base: reportConfig.api_base,
          model: reportConfig.model,
          api_key: reportConfig.api_key || null,
        }),
      });
      setReportConfig((previous) => ({ ...previous, ...data, api_key: "" }));
      setReportMessage(data.configured ? "DeepSeek 配置已保存。API Key 不会回传到页面，仅显示掩码。" : "配置已保存，但尚未填写 API Key。 ");
    } catch (error) {
      setReportMessage(`配置保存失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function generateIntelligenceReport() {
    setBusy(true);
    try {
      const report = await requestJson("/api/intelligence/reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ camera_id: selectedCameraId || null }),
      });
      setReports((previous) => [report, ...previous.filter((item) => item.id !== report.id)]);
      setActiveReportId(report.id);
      setReportMessage("智能分析报告已生成并写入 SQLite 历史库。");
      addLog(`已生成智能分析报告：${selectedCamera?.name || selectedCameraId || "当前视角"}`);
    } catch (error) {
      setReportMessage(`生成失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteIntelligenceReport(reportId) {
    setBusy(true);
    try {
      await requestJson(`/api/intelligence/reports/${reportId}`, { method: "DELETE" });
      setReports((previous) => {
        const next = previous.filter((item) => item.id !== reportId);
        setActiveReportId((active) => (active === reportId ? next[0]?.id || null : active));
        return next;
      });
      setReportMessage("报告已删除。");
    } catch (error) {
      setReportMessage(`删除失败：${error.message}`);
    } finally {
      setBusy(false);
    }
  }

  const visibleCameras = cameras.slice(0, 12);
  const algorithmState = dashboard?.algorithm;
  const algorithmReady = algorithmState?.status === "ready";
  const isAdmin = currentUser?.role === "admin";
  const activeRoadEventTypes = new Set(["road_obstacle", "road_damage", "road_pedestrian"]);
  const activeRoadEventKeys = new Set(
    (analysis.events || [])
      .filter((event) => activeRoadEventTypes.has(event.type))
      .map((event) => `${event.type}|${event.camera_id || ""}|${event.description}`),
  );
  const allEvents = uniqueEvents([
    ...(analysis.events || []),
    ...(dashboard?.events || []).filter((event) => {
      if (!activeRoadEventTypes.has(event.type)) return true;
      return activeRoadEventKeys.has(`${event.type}|${event.camera_id || ""}|${event.description}`);
    }),
  ]);
  const illegalStopEvents = allEvents.filter((event) => event.type === "illegal_stop").slice(0, 4);
  const mergedEvents = allEvents.filter((event) => event.type !== "illegal_stop").slice(0, 8);
  const roadAnomalyCount = (analysis.events || []).filter((event) =>
    ["road_obstacle", "road_damage", "road_pedestrian"].includes(event.type),
  ).length;
  const filteredWhitelist = whitelist.filter((item) => {
    const query = whitelistQuery.trim().toLowerCase();
    if (!query) return true;
    return [item.plate_no, item.owner, item.note].some((value) => String(value || "").toLowerCase().includes(query));
  });
  const activeReport = reports.find((item) => item.id === activeReportId) || reports[0] || null;

  return (
    <main className="app-shell">
      {!currentUser ? (
        <section className="auth-page">
          <form className="auth-card" onSubmit={submitAuth}>
            <div className="brand auth-brand">
              <span>
                <Route size={26} />
              </span>
              <div>
                <h1>STrans 系统登录</h1>
                <p>沙盘交通监控 · 用户权限管理 · 数据持久化</p>
              </div>
            </div>
            <div className="auth-tabs">
              <button
                type="button"
                className={cx(authMode === "login" && "active")}
                onClick={() => {
                  setAuthMode("login");
                  setAuthForm({ username: "admin", password: "admin123", captcha_code: "" });
                  loadCaptcha();
                }}
              >
                登录
              </button>
              <button
                type="button"
                className={cx(authMode === "register" && "active")}
                onClick={() => {
                  setAuthMode("register");
                  setAuthForm({ username: "", password: "", captcha_code: "" });
                  loadCaptcha();
                }}
              >
                注册
              </button>
            </div>
            <label htmlFor="authUsername">用户名</label>
            <input
              id="authUsername"
              value={authForm.username}
              onChange={(event) => setAuthForm((prev) => ({ ...prev, username: event.target.value }))}
              placeholder="请输入用户名"
              autoComplete="username"
            />
            <label htmlFor="authPassword">密码</label>
            <input
              id="authPassword"
              type="password"
              value={authForm.password}
              onChange={(event) => setAuthForm((prev) => ({ ...prev, password: event.target.value }))}
              placeholder="请输入密码"
              autoComplete={authMode === "login" ? "current-password" : "new-password"}
            />
            <label htmlFor="captchaCode">图片验证码</label>
            <div className="captcha-row">
              <input
                id="captchaCode"
                value={authForm.captcha_code}
                onChange={(event) => setAuthForm((prev) => ({ ...prev, captcha_code: event.target.value }))}
                placeholder="输入右侧验证码"
              />
              {captcha.image ? <img src={captcha.image} alt="验证码" onClick={loadCaptcha} /> : <button type="button" onClick={loadCaptcha}>刷新</button>}
            </div>
            {authMessage && <p className="auth-message">{authMessage}</p>}
            <button type="submit" className="primary auth-submit" disabled={busy}>
              {authMode === "login" ? "登录系统" : "注册普通用户"}
            </button>
            <p className="hint">普通用户只能查看监控、历史等基础功能；管理功能需要管理员权限。</p>
          </form>
        </section>
      ) : (
      <>
      <header className="topbar">
        <div className="brand">
          <span>
            <Route size={26} />
          </span>
          <div>
            <h1>STrans 沙盘交通监控大屏</h1>
            <p>多路 RTSP 摄像头 · 手机视频源 · 本地模型检测 · 历史记录归档</p>
          </div>
        </div>
        <div className="topbar-status">
          <button type="button" className={cx("nav-switch", viewMode === "monitor" && "active")} onClick={() => setViewMode("monitor")}>
            实时监控
          </button>
          <button type="button" className={cx("nav-switch", FEATURE_VIEWS.has(viewMode) && "active")} onClick={() => setViewMode("history")}>
            功能中心
          </button>
          <button type="button" className={cx("nav-switch", viewMode === "reports" && "active")} onClick={() => setViewMode("reports")}>
            智能报告
          </button>
          <span className={cx("service-pill", isAdmin ? "ok" : "idle")}>
            <CheckCircle2 size={16} />
            {currentUser.username}：{isAdmin ? "管理员" : "普通用户"}
          </span>
          <button type="button" className="nav-switch" onClick={logout}>
            退出
          </button>
          <span className={cx("service-pill", algorithmReady ? "ok" : "warn")}>
            {algorithmReady ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
            算法服务：{algorithmStatusText(algorithmState?.status)}
          </span>
          <span
            className={cx("service-pill", selectedStatus?.connected ? "ok" : selectedStatus?.last_error ? "warn" : "idle")}
            title={selectedStatus?.last_error || statusText(selectedStatus)}
          >
            {selectedStatus?.connected ? <Wifi size={16} /> : <WifiOff size={16} />}
            当前画面：{statusText(selectedStatus)}
          </span>
        </div>
      </header>

      {FEATURE_VIEWS.has(viewMode) && (
        <nav className="feature-center-nav" aria-label="功能中心">
          <strong><Settings2 size={17} />功能中心</strong>
          <button type="button" className={cx(viewMode === "analytics" && "active")} onClick={() => setViewMode("analytics")}><BarChart3 size={15} />数据趋势</button>
          <button type="button" className={cx(viewMode === "history" && "active")} onClick={() => setViewMode("history")}><Database size={15} />历史记录</button>
          <button type="button" className={cx(viewMode === "incidents" && "active")} onClick={() => setViewMode("incidents")}><Bell size={15} />告警处置</button>
          <button type="button" className={cx(viewMode === "account" && "active")} onClick={() => setViewMode("account")}><KeyRound size={15} />账号安全</button>
          <button type="button" className={cx(viewMode === "whitelist" && "active")} onClick={() => setViewMode("whitelist")}><ShieldCheck size={15} />白名单</button>
          {isAdmin && <button type="button" className={cx(viewMode === "cameras" && "active")} onClick={() => setViewMode("cameras")}><Camera size={15} />摄像头</button>}
          {isAdmin && <button type="button" className={cx(viewMode === "models" && "active")} onClick={() => setViewMode("models")}><ServerCog size={15} />模型配置</button>}
          {isAdmin && <button type="button" className={cx(viewMode === "scheduler" && "active")} onClick={() => setViewMode("scheduler")}><Activity size={15} />智能调度</button>}
          {isAdmin && <button type="button" className={cx(viewMode === "users" && "active")} onClick={() => setViewMode("users")}><Users size={15} />用户管理</button>}
          {isAdmin && <button type="button" className={cx(viewMode === "audit" && "active")} onClick={() => setViewMode("audit")}><FileText size={15} />审计日志</button>}
          <button type="button" className={cx(viewMode === "roadmodeler" && "active")} onClick={() => setViewMode("roadmodeler")}><Route size={15} />道路建模工具</button>
        </nav>
      )}
      {FEATURE_VIEWS.has(viewMode) && featureMessage && <p className="feature-message">{featureMessage}</p>}

      {viewMode === "analytics" ? (
        <DetectionTrendView records={history} />
      ) : viewMode === "history" ? (
        <section className="history-page">
          <Panel
            title="历史记录与报告导出"
            icon={<Database size={18} />}
            action={
              <div className="main-actions">
                <button type="button" className="download-link" onClick={() => downloadHistory("csv")}>
                  <Download size={15} />
                  导出 CSV
                </button>
                <button type="button" className="download-link" onClick={() => downloadHistory("json")}>
                  <Download size={15} />
                  导出 JSON
                </button>
              </div>
            }
          >
            <div className="history-table">
              <div className="history-table-head">
                <span>时间</span>
                <span>摄像头</span>
                <span>模型</span>
                <span>车辆</span>
                <span>检测框</span>
                <span>事件</span>
                <span>车牌</span>
                <span>白名单</span>
                <span>拥堵</span>
                <span>耗时</span>
                <span>操作</span>
              </div>
              {history.length ? (
                history.map((item) => (
                  <div className="history-row" key={item.id}>
                    <span>{item.created_at?.replace("T", " ")}</span>
                    <strong>{item.camera_id || "--"}</strong>
                    <span>{item.model_id || "--"}</span>
                    <em>{item.vehicle_count}</em>
                    <span>{item.detection_count}</span>
                    <span>{item.event_count}</span>
                    <span>{item.plates || "--"}</span>
                    <span>{(item.whitelist_pass_count || 0) + "/" + (item.whitelist_block_count || 0)}</span>
                    <span>{congestionText(item.congestion_level)}</span>
                    <span>{item.inference_ms == null ? "--" : `${item.inference_ms} ms`}</span>
                    <span>{isAdmin ? <button type="button" className="table-delete" onClick={() => deleteHistoryRecord(item.id)}><Trash2 size={13} />删除</button> : "只读"}</span>
                  </div>
                ))
              ) : (
                <p className="empty-copy history-empty">暂无历史记录。收到模型检测结果后会自动写入 SQLite。</p>
              )}
            </div>
          </Panel>
        </section>
      ) : viewMode === "reports" ? (
        <section className="report-page">
          <Panel
            title="DeepSeek 智能分析报告"
            icon={<Sparkles size={18} />}
            action={
              isAdmin ? (
                <button type="button" className="primary" disabled={busy || !reportConfig.configured} onClick={generateIntelligenceReport}>
                  <Sparkles size={16} />
                  生成本次报告
                </button>
              ) : null
            }
          >
            <div className="report-page-layout">
              <aside className="report-side">
                {isAdmin && (
                  <section className="report-config">
                    <h3>DeepSeek API 配置</h3>
                    <label htmlFor="deepseekBase">API 地址</label>
                    <input
                      id="deepseekBase"
                      value={reportConfig.api_base}
                      onChange={(event) => setReportConfig((previous) => ({ ...previous, api_base: event.target.value }))}
                    />
                    <label htmlFor="deepseekModel">模型名称</label>
                    <input
                      id="deepseekModel"
                      value={reportConfig.model}
                      onChange={(event) => setReportConfig((previous) => ({ ...previous, model: event.target.value }))}
                    />
                    <label htmlFor="deepseekKey">API Key</label>
                    <input
                      id="deepseekKey"
                      type="password"
                      value={reportConfig.api_key}
                      onChange={(event) => setReportConfig((previous) => ({ ...previous, api_key: event.target.value }))}
                      placeholder={reportConfig.api_key_masked ? `已配置：${reportConfig.api_key_masked}` : "输入 DeepSeek API Key"}
                      autoComplete="new-password"
                    />
                    <button type="button" onClick={saveReportConfig} disabled={busy}>
                      保存配置
                    </button>
                    <p className="hint">密钥只用于本机后端请求，不会回传到浏览器。默认使用 DeepSeek Chat Completions 接口。</p>
                  </section>
                )}
                {!isAdmin && <p className="permission-note">普通用户可查看已归档报告；生成报告和 API 配置仅限管理员。</p>}
                <section className="report-list" aria-label="报告历史">
                  <h3>报告归档</h3>
                  {reports.length ? reports.map((report) => (
                    <button
                      type="button"
                      key={report.id}
                      className={cx("report-list-item", activeReport?.id === report.id && "active")}
                      onClick={() => setActiveReportId(report.id)}
                    >
                      <FileText size={16} />
                      <span>
                        <strong>{report.title}</strong>
                        <small>{report.created_at?.replace("T", " ")} · {report.model}</small>
                      </span>
                    </button>
                  )) : <p className="empty-copy">暂无报告。管理员可在配置 API 后生成当前检测成果的分析报告。</p>}
                </section>
              </aside>
              <article className="report-content">
                {reportMessage && <p className="whitelist-message">{reportMessage}</p>}
                {activeReport ? (
                  <>
                    <header className="report-content-head">
                      <div>
                        <h2>{activeReport.title}</h2>
                        <p>{activeReport.created_at?.replace("T", " ")} · {activeReport.created_by || "系统"} · {activeReport.model}</p>
                      </div>
                      {isAdmin && (
                        <button type="button" className="report-delete" disabled={busy} onClick={() => deleteIntelligenceReport(activeReport.id)}>
                          <Trash2 size={15} />
                          删除
                        </button>
                      )}
                    </header>
                    <div className="report-markdown">{activeReport.content}</div>
                  </>
                ) : (
                  <div className="report-empty">
                    <FileText size={42} />
                    <h2>等待生成智能分析报告</h2>
                    <p>报告将基于当前检测结果、车道拥堵状态、事件日志、近期历史记录和天气信息生成。</p>
                  </div>
                )}
              </article>
            </div>
          </Panel>
        </section>
      ) : viewMode === "account" ? (
        <section className="feature-page account-page">
          <Panel title="账号安全" icon={<KeyRound size={18} />}>
            <div className="account-layout">
              <div className="account-summary">
                <span><strong>当前用户</strong><em>{currentUser.username}</em></span>
                <span><strong>账号角色</strong><em>{isAdmin ? "管理员" : "普通用户"}</em></span>
                <span><strong>最近登录</strong><em>{currentUser.last_login_at?.replace("T", " ") || "本次首次登录"}</em></span>
                <span><strong>会话有效期</strong><em>12 小时</em></span>
              </div>
              <form className="account-password-form" onSubmit={changeOwnPassword}>
                <h3>修改登录密码</h3>
                <label htmlFor="oldPassword">原密码</label>
                <input id="oldPassword" type="password" autoComplete="current-password" value={passwordForm.old_password} onChange={(event) => setPasswordForm((previous) => ({ ...previous, old_password: event.target.value }))} />
                <label htmlFor="newPassword">新密码</label>
                <input id="newPassword" type="password" autoComplete="new-password" minLength={6} value={passwordForm.new_password} onChange={(event) => setPasswordForm((previous) => ({ ...previous, new_password: event.target.value }))} />
                <button type="submit" className="primary" disabled={busy || !passwordForm.old_password || passwordForm.new_password.length < 6}>修改密码</button>
                <p className="hint">修改成功后，当前账号的所有登录会话都会失效，需要重新登录。</p>
              </form>
            </div>
          </Panel>
        </section>
      ) : viewMode === "incidents" ? (
        <section className="feature-page incident-page">
          <Panel title="告警处置中心" icon={<Bell size={18} />} action={<button type="button" onClick={loadFeatureData}><RefreshCcw size={15} />刷新</button>}>
            <div className="incident-table">
              <div className="incident-table-head"><span>时间</span><span>摄像头</span><span>类型</span><span>级别</span><span>告警内容</span><span>状态</span><span>处置备注</span><span>操作</span></div>
              {incidents.length ? incidents.map((item) => (
                <div className="incident-row" key={item.event_id}>
                  <span>{item.created_at?.replace("T", " ")}</span>
                  <strong>{item.camera_id || "--"}</strong>
                  <span>{item.event_type}</span>
                  <em className={cx("severity-tag", item.severity)}>{severityText(item.severity)}</em>
                  <span title={item.description}>{item.description}</span>
                  <em className={cx("incident-status", item.status)}>{({ pending: "待处理", confirmed: "已确认", resolved: "已解除", false_positive: "误报" })[item.status] || item.status}</em>
                  <input value={incidentNotes[item.event_id] ?? item.note ?? ""} onChange={(event) => setIncidentNotes((previous) => ({ ...previous, [item.event_id]: event.target.value }))} placeholder="填写处置说明" />
                  <div className="incident-actions">
                    <button type="button" className="evidence-button" onClick={() => downloadEvidencePackage(item.event_id)}><PackageCheck size={13} />证据包</button>
                    <button type="button" onClick={() => handleIncident(item.event_id, "confirmed")}>确认</button>
                    <button type="button" onClick={() => handleIncident(item.event_id, "resolved")}>解除</button>
                    <button type="button" onClick={() => handleIncident(item.event_id, "false_positive")}>误报</button>
                  </div>
                </div>
              )) : <p className="empty-copy history-empty">暂无持久化告警。新的道路异常、禁停和白名单告警会自动进入处置中心。</p>}
            </div>
          </Panel>
        </section>
      ) : viewMode === "scheduler" && isAdmin ? (
        <section className="feature-page scheduler-page">
          <Panel
            title="自适应模型调度"
            icon={<Activity size={18} />}
            action={<button type="button" className={cx("scheduler-toggle", schedulerState.enabled && "enabled")} disabled={busy} onClick={toggleAdaptiveScheduler}>{schedulerState.enabled ? "自动调度中" : "人工参数"}</button>}
          >
            <div className="scheduler-layout">
              <section className="scheduler-overview">
                <h3>调度原则</h3>
                <p>根据任务类型、静态/实时来源、CPU、内存、GPU、显存和最新推理耗时选择策略。策略仅在档位变化时记录，资源采样带缓存，不增加逐帧监控负担。</p>
                <div className="scheduler-profile-grid">
                  <span><strong>质量优先</strong><em>GPU 余量充足或静态图片，提高推理尺寸</em></span>
                  <span><strong>均衡模式</strong><em>日常实时视频使用人工参数附近的稳定配置</em></span>
                  <span><strong>实时优先</strong><em>推理耗时或 GPU 负载较高时降低计算量</em></span>
                  <span><strong>保护模式</strong><em>资源接近上限时切换备用模型并降低频率</em></span>
                </div>
              </section>
              <section className="scheduler-active">
                <h3>当前摄像头策略</h3>
                {(schedulerState.active || []).length ? schedulerState.active.map((item) => (
                  <article key={item.camera_id}>
                    <header><strong>{item.camera_id}</strong><em className={`profile-${item.profile}`}>{item.profile}</em></header>
                    <p>{item.reason}</p>
                    <div><span>模型 {item.model_name}</span><span>尺寸 {item.inference_size}</span><span>间隔 {item.detection_interval_ms} ms</span><span>置信度 {item.confidence}</span></div>
                  </article>
                )) : <p className="empty-copy">启动模型画面后将显示实时调度策略。</p>}
              </section>
            </div>
            <div className="scheduler-history">
              <h3>策略切换记录</h3>
              <div className="scheduler-history-head"><span>时间</span><span>摄像头</span><span>任务</span><span>策略</span><span>参数</span><span>触发原因</span></div>
              {(schedulerState.decisions || []).length ? schedulerState.decisions.map((item, index) => (
                <div className="scheduler-history-row" key={`${item.timestamp}-${item.camera_id}-${index}`}><span>{item.timestamp?.replace("T", " ")}</span><strong>{item.camera_id}</strong><span>{item.task_mode}</span><em>{item.profile}</em><span>{item.model_name} / {item.inference_size}px / {item.detection_interval_ms}ms</span><span>{item.reason}</span></div>
              )) : <p className="empty-copy">暂无策略切换记录。</p>}
            </div>
          </Panel>
        </section>
      ) : viewMode === "cameras" && isAdmin ? (
        <section className="feature-page camera-management-page">
          <Panel title="摄像头设备管理" icon={<Camera size={18} />}>
            <div className="camera-management-layout">
              <form className="camera-management-form" onSubmit={saveManagedCamera}>
                <h3>{cameraForm.camera_id ? `编辑 ${cameraForm.camera_id}` : "新增摄像头"}</h3>
                <label htmlFor="managedCameraName">名称</label>
                <input id="managedCameraName" required value={cameraForm.name} onChange={(event) => setCameraForm((previous) => ({ ...previous, name: event.target.value }))} />
                <label htmlFor="managedCameraType">类型</label>
                <select id="managedCameraType" value={cameraForm.type} onChange={(event) => setCameraForm((previous) => ({ ...previous, type: event.target.value }))}><option value="custom">自定义</option><option value="phone">手机</option><option value="esp32cam">ESP32-CAM</option><option value="usb">USB 摄像头</option><option value="sandtable">沙盘 RTSP</option></select>
                <label htmlFor="managedCameraUrl">视频流地址</label>
                <input id="managedCameraUrl" required value={cameraForm.stream_url} onChange={(event) => setCameraForm((previous) => ({ ...previous, stream_url: event.target.value }))} placeholder="RTSP、HTTP、文件路径或摄像头编号" />
                <label htmlFor="managedCameraLocation">位置</label>
                <input id="managedCameraLocation" required value={cameraForm.location} onChange={(event) => setCameraForm((previous) => ({ ...previous, location: event.target.value }))} />
                <label htmlFor="managedCameraDescription">说明</label>
                <textarea id="managedCameraDescription" value={cameraForm.description} onChange={(event) => setCameraForm((previous) => ({ ...previous, description: event.target.value }))} />
                <div className="form-actions"><button type="submit" className="primary" disabled={busy}>保存配置</button>{cameraForm.camera_id && <button type="button" onClick={clearCameraForm}>取消编辑</button>}</div>
              </form>
              <div className="managed-camera-list">
                <div className="managed-camera-head"><span>设备</span><span>位置</span><span>类型</span><span>状态</span><span>地址</span><span>操作</span></div>
                {cameras.map((camera) => (
                  <div className="managed-camera-row" key={camera.camera_id}>
                    <strong>{camera.name}<small>{camera.camera_id}</small></strong>
                    <span>{camera.location}</span><span>{camera.type}</span><em>{camera.status}</em><span title={camera.stream_url}>{camera.stream_url}</span>
                    <div><button type="button" onClick={() => editManagedCamera(camera)}>编辑</button><button type="button" onClick={() => testManagedCamera(camera.camera_id)}>测试</button>{!camera.camera_id.startsWith("live") && <button type="button" className="danger" onClick={() => deleteManagedCamera(camera.camera_id)}>删除</button>}</div>
                  </div>
                ))}
              </div>
            </div>
          </Panel>
        </section>
      ) : viewMode === "users" && isAdmin ? (
        <section className="feature-page user-management-page">
          <Panel title="用户与权限管理" icon={<Users size={18} />} action={<button type="button" onClick={loadFeatureData}><RefreshCcw size={15} />刷新</button>}>
            <div className="user-table">
              <div className="user-table-head"><span>用户名</span><span>角色</span><span>状态</span><span>创建时间</span><span>最后登录</span><span>重置密码</span><span>操作</span></div>
              {systemUsers.length ? systemUsers.map((item) => (
                <div className="user-row" key={item.id}>
                  <strong>{item.username}</strong>
                  <select value={item.role} disabled={item.id === currentUser.id} onChange={(event) => updateSystemUser(item.id, { role: event.target.value })}><option value="user">普通用户</option><option value="admin">管理员</option></select>
                  <button type="button" className={cx("status-toggle", item.enabled && "enabled")} disabled={item.id === currentUser.id} onClick={() => updateSystemUser(item.id, { enabled: !item.enabled })}>{item.enabled ? "已启用" : "已禁用"}</button>
                  <span>{item.created_at?.replace("T", " ")}</span><span>{item.last_login_at?.replace("T", " ") || "尚未登录"}</span>
                  <div className="password-reset"><input type="password" value={resetPasswords[item.id] || ""} onChange={(event) => setResetPasswords((previous) => ({ ...previous, [item.id]: event.target.value }))} placeholder="至少 6 位" /><button type="button" onClick={() => resetSystemUserPassword(item.id)}>重置</button></div>
                  <button type="button" className="table-delete" disabled={item.id === currentUser.id || item.username === "admin"} onClick={() => deleteSystemUser(item.id)}><Trash2 size={13} />删除</button>
                </div>
              )) : <p className="empty-copy history-empty">正在加载用户数据。</p>}
            </div>
          </Panel>
        </section>
      ) : viewMode === "audit" && isAdmin ? (
        <section className="feature-page audit-page">
          <Panel title="系统操作审计" icon={<FileText size={18} />} action={<button type="button" onClick={loadFeatureData}><RefreshCcw size={15} />刷新</button>}>
            <div className="audit-table">
              <div className="audit-table-head"><span>时间</span><span>操作用户</span><span>动作</span><span>目标</span><span>详情</span></div>
              {auditLogs.length ? auditLogs.map((item) => <div className="audit-row" key={item.id}><span>{item.created_at?.replace("T", " ")}</span><strong>{item.username}</strong><em>{item.action}</em><span>{item.target || "--"}</span><span title={item.detail}>{item.detail || "--"}</span></div>) : <p className="empty-copy history-empty">暂无审计记录。白名单、模型、摄像头、用户和历史数据变更会记录在这里。</p>}
            </div>
          </Panel>
        </section>
      ) : viewMode === "models" && isAdmin ? (
        <section className="model-page">
          <Panel title="模型选择与参数配置" icon={<ServerCog size={18} />}>
            <div className="model-config-layout">
              <div className="model-form">
                <label htmlFor="modelName">本地演示模型</label>
                <select
                  id="modelName"
                  value={selectedModelName}
                  onChange={(event) => {
                    setSelectedModelName(event.target.value);
                    setStreamVersion(Date.now());
                  }}
                >
                  <option value="auto">自动选择 YOLO11s</option>
                  <option value="visdrone">YOLO11s-VisDrone</option>
                  <option value="fallback">备用模型</option>
                </select>

                <label htmlFor="modelConfidence">检测置信度</label>
                <input
                  id="modelConfidence"
                  type="number"
                  min="0.05"
                  max="0.95"
                  step="0.05"
                  value={modelConfig.confidence}
                  onChange={(event) => updateModelConfig("confidence", Number(event.target.value))}
                />

                <label htmlFor="modelIou">IOU 阈值</label>
                <input
                  id="modelIou"
                  type="number"
                  min="0.1"
                  max="0.9"
                  step="0.05"
                  value={modelConfig.iou}
                  onChange={(event) => updateModelConfig("iou", Number(event.target.value))}
                />

                <label htmlFor="modelInterval">检测间隔 ms</label>
                <input
                  id="modelInterval"
                  type="number"
                  min="100"
                  max="5000"
                  step="100"
                  value={modelConfig.detection_interval_ms}
                  onChange={(event) => updateModelConfig("detection_interval_ms", Number(event.target.value))}
                />

                <label htmlFor="modelSize">推理尺寸</label>
                <input
                  id="modelSize"
                  type="number"
                  min="256"
                  max="1280"
                  step="64"
                  value={modelConfig.inference_size}
                  onChange={(event) => updateModelConfig("inference_size", Number(event.target.value))}
                />

                <button type="button" className="primary" disabled={busy} onClick={saveModelConfig}>
                  保存模型参数
                </button>
                {modelMessage && <p className="whitelist-message">{modelMessage}</p>}
              </div>

              <div className="model-form">
                <div className="model-status-list">
                  <span><strong>算法状态</strong><em>{algorithmStatusText(algorithmState?.status)}</em></span>
                  <span><strong>当前模型</strong><em>{selectedModelName}</em></span>
                  <span><strong>启用任务</strong><em>{(modelConfig.enabled_tasks || []).join(" / ")}</em></span>
                  <span><strong>说明</strong><em>模型参数保存到本机后端配置，实时画面刷新后生效。</em></span>
                </div>
              </div>
            </div>
          </Panel>
        </section>
      ) : viewMode === "whitelist" ? (
        <section className="whitelist-page">
          <Panel
            title="白名单车辆管理"
            icon={<CheckCircle2 size={18} />}
            action={
              <div className="whitelist-search">
                <input
                  value={whitelistSearchText}
                  onChange={(event) => setWhitelistSearchText(event.target.value)}
                  placeholder="查询车牌、车主或备注"
                />
                <button type="button" onClick={() => setWhitelistQuery(whitelistSearchText)}>
                  查询
                </button>
                <button
                  type="button"
                  onClick={async () => {
                    setWhitelistSearchText("");
                    setWhitelistQuery("");
                    setWhitelistMessage("已刷新白名单数据");
                    await refresh();
                  }}
                >
                  重置
                </button>
              </div>
            }
          >
            {!isAdmin && <p className="permission-note">当前为普通用户，只能查看白名单记录，不能新增或删除。</p>}
            <div className={cx("whitelist-management", !isAdmin && "readonly")}>
              {isAdmin && (
              <form
                className="whitelist-form"
                onSubmit={(event) => {
                  event.preventDefault();
                  addWhitelistPlate();
                }}
              >
                <label htmlFor="whitelistPlate">车牌号</label>
                <input
                  id="whitelistPlate"
                  value={whitelistPlate}
                  onChange={(event) => setWhitelistPlate(event.target.value)}
                  placeholder="例如 京K9134J"
                />
                <label htmlFor="whitelistOwner">车主/车辆说明</label>
                <input
                  id="whitelistOwner"
                  value={whitelistOwner}
                  onChange={(event) => setWhitelistOwner(event.target.value)}
                  placeholder="例如 沙盘白名单车辆"
                />
                <label htmlFor="whitelistNote">备注</label>
                <input
                  id="whitelistNote"
                  value={whitelistNote}
                  onChange={(event) => setWhitelistNote(event.target.value)}
                  placeholder="例如 准入车牌"
                />
                <button type="submit" className="primary" disabled={busy || !whitelistPlate.trim()}>
                  保存到数据库
                </button>
                {whitelistMessage && <p className="whitelist-message">{whitelistMessage}</p>}
                <p className="hint">保存后会立即参与车牌检测放行判断，命中白名单时实时结果显示“可通过”。</p>
              </form>
              )}

              <div className="whitelist-table">
                <div className="whitelist-table-head">
                  <span>车牌号</span>
                  <span>车主/说明</span>
                  <span>备注</span>
                  <span>状态</span>
                  <span>更新时间</span>
                  <span>操作</span>
                </div>
                {filteredWhitelist.length ? (
                  filteredWhitelist.map((item) => (
                    <div className="whitelist-row" key={item.plate_no}>
                      <strong>{item.plate_no}</strong>
                      <span>{item.owner || "--"}</span>
                      <span>{item.note || "--"}</span>
                      <em>{item.enabled ? "可通过" : "停用"}</em>
                      <span>{item.updated_at?.replace("T", " ") || "--"}</span>
                      {isAdmin ? (
                        <button type="button" disabled={busy} onClick={() => removeWhitelistPlate(item.plate_no)}>
                          <X size={14} />
                          删除
                        </button>
                      ) : (
                        <span>只读</span>
                      )}
                    </div>
                  ))
                ) : (
                  <p className="empty-copy history-empty">没有匹配的白名单记录。可以在左侧新增车牌，数据会写入 SQLite。</p>
                )}
              </div>
            </div>
          </Panel>
        </section>
      ) : viewMode === "roadmodeler" ? (
        <section className="roadmodeler-page">
          <Panel title="道路逻辑建模工具" icon={<Route size={18} />} action={
            <div className="roadmodeler-actions">
              <button type="button" onClick={() => window.open(ROAD_MODELER_URL, "_blank")}>
                在新窗口打开
              </button>
            </div>
          }>
            <div className="roadmodeler-iframe-wrap">
              <iframe
                src={ROAD_MODELER_URL}
                title="道路逻辑建模工具"
                sandbox="allow-scripts allow-same-origin allow-forms"
                loading="lazy"
              />
            </div>
          </Panel>
        </section>
      ) : (
        <>

      <section className="metrics-row">
        <Metric label="当前摄像头" value={selectedCamera?.name || "--"} hint={selectedCamera?.location || "未选择"} />
        <Metric
          label={analysisMode === "road_anomaly" ? "异常目标" : "车辆数量"}
          value={analysisMode === "road_anomaly" ? (analysis.detections || []).length : (stats.vehicle_count || stats.current_count || 0)}
          hint={analysisMode === "road_anomaly" ? "道路异常模式实时结果" : "实时视频流模型统计"}
          tone="green"
        />
        <Metric
          label={analysisMode === "road_anomaly" ? "当前模式" : "平均速度"}
          value={analysisMode === "road_anomaly" ? "道路异常" : stats.avg_speed == null ? "--" : `${stats.avg_speed} ${stats.avg_speed_unit || "cm/s"}`}
          hint={analysisMode === "road_anomaly" ? "不统计车流速度、热力和禁停" : stats.avg_speed == null ? "等待稳定轨迹" : stats.speed_estimated ? "按主视角标定估算" : "主视角实测标定"}
          tone="cyan"
        />
        <Metric
          label={analysisMode === "road_anomaly" ? "异常状态" : "拥堵等级"}
          value={analysisMode === "road_anomaly" ? (roadAnomalyCount ? "待复核" : "未发现") : congestionText(stats.congestion_level)}
          hint={analysisMode === "road_anomaly" ? "异物、行人和路面损坏独立检测" : `密度 ${stats.density ?? "--"}`}
          tone="orange"
        />
        <Metric label="道路异常" value={roadAnomalyCount} hint={analysis.timestamp?.replace("T", " ") || analysis.model_id || "等待模型结果"} tone="purple" />
      </section>

      <ResourceMonitor resources={resources} />

      <section className="layout">
        <aside className="left-column">
          <WeatherPanel weather={weather} />
          <Panel title="摄像头控制" icon={<Radio size={18} />} className="camera-control-panel">
            <div className="camera-control">
              <label htmlFor="cameraSelect">选择摄像头</label>
              <select
                id="cameraSelect"
                value={selectedCameraId || ""}
                onChange={(event) => {
                  setSelectedCameraId(event.target.value);
                  setStreamVersion(Date.now());
                }}
              >
                {visibleCameras.map((camera) => (
                  <option key={camera.camera_id} value={camera.camera_id}>
                    {camera.name} · {camera.location}
                  </option>
                ))}
              </select>
              <div className="selected-camera-summary">
                <span className="camera-icon"><Camera size={16} /></span>
                <div>
                  <strong>{selectedCamera?.name || "未选择摄像头"}</strong>
                  <small>{selectedCamera?.location || "请选择一路摄像头"}</small>
                </div>
                <em className={cx(selectedStatus?.connected && "online")}>{selectedStatus?.connected ? "在线" : "未启动"}</em>
              </div>
              <div className="selected-camera-actions">
                <button type="button" disabled={busy || !selectedCamera} onClick={() => startCamera(selectedCamera.camera_id)}>
                  <Play size={15} />
                  启动
                </button>
                <button type="button" disabled={busy || !selectedCamera} onClick={() => stopCamera(selectedCamera.camera_id)}>
                  <Square size={14} />
                  停止
                </button>
              </div>
              <div className="voice-control-row">
                <button
                  type="button"
                  className={cx("voice-control", voiceListening && "listening")}
                  onClick={startVoiceRecognition}
                  title="使用语音切换摄像头、任务模式或查询白名单"
                >
                  <Mic size={16} />
                  {voiceListening ? "正在聆听" : "语音识别"}
                </button>
                <small aria-live="polite">{voiceMessage}</small>
                <details className="voice-command-guide">
                  <summary>可用语音指令</summary>
                  <div>
                    <span>切换到3号摄像头</span>
                    <span>启动3号摄像头 / 停止3号摄像头</span>
                    <span>停止当前摄像头</span>
                    <span>打开道路异常模式 / 打开车辆监控模式</span>
                    <span>分析当前帧 / 刷新实时画面</span>
                    <span>查看历史记录 / 打开白名单 / 打开模型配置</span>
                    <span>查看智能报告 / 返回实时监控</span>
                    <span>查看热力图 / 关闭热力图</span>
                    <span>查询今天白名单通过几辆</span>
                  </div>
                </details>
              </div>
            </div>
          </Panel>
          <Panel title="视频源接入" icon={<ServerCog size={18} />} className="camera-input-panel">
            <div className="form-block">
              <label htmlFor="phoneUrl">手机视频地址</label>
              <input id="phoneUrl" value={phoneUrl} onChange={(event) => setPhoneUrl(event.target.value)} />
              <button type="button" className="primary" disabled={busy} onClick={connectPhone}>
                接入手机画面
              </button>
            </div>
          </Panel>
        </aside>

        <section className="main-column">
          <Panel
            className="main-video-panel"
            title={selectedCamera ? `${selectedCamera.name} 实时画面` : "实时画面"}
            icon={<Eye size={18} />}
            action={
              <div className="main-actions">
                <div className="analysis-mode-switch" role="group" aria-label="检测任务模式">
                  <button type="button" className={cx(analysisMode === "traffic" && "active")} onClick={() => switchAnalysisMode("traffic")}>
                    车辆监控
                  </button>
                  <button type="button" className={cx(analysisMode === "road_anomaly" && "active")} onClick={() => switchAnalysisMode("road_anomaly")}>
                    道路异常
                  </button>
                </div>
                <button type="button" disabled={busy || !selectedCamera} onClick={() => startCamera(selectedCamera.camera_id)}>
                  <Play size={16} />
                  启动
                </button>
                <button type="button" disabled={busy || !selectedCamera} onClick={inferOnce}>
                  <Activity size={16} />
                  {analysisMode === "road_anomaly" ? "分析异常帧" : "分析当前帧"}
                </button>
                <button type="button" onClick={() => setStreamVersion(Date.now())}>
                  <RefreshCcw size={16} />
                  刷新
                </button>
              </div>
            }
          >
            <div className="video-info">
              <span>{selectedCamera?.stream_url || "请选择摄像头"}</span>
              <span>
                {selectedStatus?.frame_width || "--"} x {selectedStatus?.frame_height || "--"} / {selectedStatus?.is_static_image ? "静态图片" : `${selectedStatus?.fps || 0} FPS`}
              </span>
            </div>
            {selectedStatus?.running && !selectedStatus?.connected && (
              <div className="stream-reconnect-notice">
                {selectedStatus.last_error || "视频流连接中，系统正在自动重连。"}
              </div>
            )}
            <div className="video-stage">
              {selectedCamera && selectedStatus?.running ? (
                <img src={streamUrl} alt={`${selectedCamera.name} 视频流`} />
              ) : (
                <div className="empty-video">
                  <Camera size={48} />
                  <h2>请选择并启动一路摄像头</h2>
                  <p>{analysisMode === "road_anomaly" ? "道路异常模式只展示异物、行人和路面损坏，不参与车辆业务统计。" : "车辆监控模式展示车辆、车牌、追踪和车流状态。"}</p>
                </div>
              )}
            </div>
          </Panel>

          <div className="preview-grid">
            {[0, 1, 2, 3].map((index) => (
              <PreviewSlot
                key={index}
                slotIndex={index}
                cameraId={previewSlots[index]}
                cameras={visibleCameras}
                statuses={statuses}
                streamVersion={streamVersion}
                onChange={changePreviewSlot}
                onSelect={(cameraId) => {
                  setSelectedCameraId(cameraId);
                  setStreamVersion(Date.now());
                }}
              />
            ))}
          </div>
        </section>

        <aside className="right-column">
          {analysisMode === "traffic" ? <Panel
            title="当前视角拥堵图"
            icon={<Flame size={18} />}
            action={
              <button type="button" className="text-action" onClick={() => setHeatmapOpen(true)}>
                查看大图
              </button>
            }
          >
            <button type="button" className="heatmap-button" onClick={() => setHeatmapOpen(true)}>
              <HeatmapView analysis={analysis} roadModel={roadModel} roadHeatmap={roadHeatmap} cameraId={selectedCameraId} />
            </button>
          </Panel> : <Panel title="道路异常识别" icon={<AlertTriangle size={18} />} className="anomaly-mode-panel">
            <div className="anomaly-mode-copy">
              <strong>独立任务模式</strong>
              <span>仅输出路面异物、路面行人和路面损坏候选。车辆数量、白名单、禁停、速度和热力图不会受该模式影响。</span>
            </div>
          </Panel>}

          {analysisMode === "traffic" && <Panel title="禁停告警" icon={<AlertTriangle size={18} />} className="event-panel stop-event-panel">
            <div className="event-list prominent">
              {illegalStopEvents.length ? (
                illegalStopEvents.map((event) => (
                  <article className="event-item warning" key={event.event_id}>
                    <div>
                      <strong>禁停告警</strong>
                      <time>{event.created_at?.replace("T", " ")}</time>
                    </div>
                    <span>{event.description}</span>
                  </article>
                ))
              ) : (
                <p className="empty-copy">车辆在禁停车道连续停留超过 30 秒后，会在此单独告警。</p>
              )}
            </div>
          </Panel>}

          <Panel title="事件日志" icon={<AlertTriangle size={18} />} className="event-panel">
            <div className="event-list prominent">
              {mergedEvents.length ? (
                mergedEvents.map((event) => (
                  <article className={cx("event-item", event.severity)} key={event.event_id}>
                    <div>
                      <strong>{severityText(event.severity)} · {event.type}</strong>
                      <time>{event.created_at?.replace("T", " ")}</time>
                    </div>
                    <span>{event.description}</span>
                  </article>
                ))
              ) : (
                <p className="empty-copy">暂无事件。道路异常、拥堵或白名单告警会在这里显示。</p>
              )}
            </div>
          </Panel>
        </aside>
      </section>

      <section className="log-strip">
        <strong>
          <BarChart3 size={16} />
          运行记录
        </strong>
        <div>
          {logs.map((log, index) => (
            <span key={String(index) + "-" + log}>{log}</span>
          ))}
        </div>
      </section>
        </>
      )}

      {heatmapOpen && (
        <div className="modal-backdrop" role="dialog" aria-modal="true">
          <section className="heatmap-modal">
            <header>
              <div>
                <h2>全局道路拥堵图</h2>
                <p>{selectedCamera?.name || "未选择摄像头"} · 检测目标 {(analysis.detections || []).length} 个 · 拥堵等级 {congestionText(stats.congestion_level)}</p>
              </div>
              <button type="button" onClick={() => setHeatmapOpen(false)} aria-label="关闭拥堵图">
                <X size={20} />
              </button>
            </header>
            <HeatmapView analysis={analysis} roadModel={roadModel} roadHeatmap={roadHeatmap} cameraId={selectedCameraId} globalView />
            <footer>
              <span>车辆先投影到对应车道，再按车道内车辆数量与平均速度计算拥堵等级。</span>
              <span>
                密度：{stats.density ?? "--"} / 平均速度：
                {stats.avg_speed == null ? "--" : `${stats.avg_speed} ${stats.avg_speed_unit || "cm/s"}`}
                {stats.avg_speed != null && stats.speed_estimated ? "（估算）" : ""}
              </span>
            </footer>
          </section>
        </div>
      )}
      </>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
