const CAMERA_CHART_COLORS = ["#0f7aa5", "#16856b", "#c76a16", "#7559a6", "#d1495b", "#64748b"];


export function buildTrendChart(records, metricKey, recordLimit) {
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
}
