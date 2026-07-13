const FRAME_CAMERA_TYPES = new Set(["phone", "esp32cam", "usb", "custom"]);

export function resolveHeatmapMode(camera) {
  const configured = camera?.heatmap_mode || "auto";
  if (configured !== "auto") return configured;
  return FRAME_CAMERA_TYPES.has(camera?.type) ? "frame" : "road";
}

export function frameHeatmapSpots(analysis, cameraId) {
  const width = Number(analysis?.source_width);
  const height = Number(analysis?.source_height);
  if (!(width > 0) || !(height > 0) || (analysis?.camera_id && analysis.camera_id !== cameraId)) return [];

  return (analysis?.detections || []).slice(0, 80).flatMap((detection) => {
    if (detection.camera_id && detection.camera_id !== cameraId) return [];
    const [x1, y1, x2, y2] = (detection.bbox || []).map(Number);
    if (![x1, y1, x2, y2].every(Number.isFinite) || x2 <= x1 || y2 <= y1) return [];
    const centerX = ((x1 + x2) / 2 / width) * 100;
    const centerY = ((y1 + y2) / 2 / height) * 100;
    if (centerX < 0 || centerX > 100 || centerY < 0 || centerY > 100) return [];
    const confidence = Math.max(0, Math.min(1, Number(detection.confidence) || 0));
    return [{
      x: Number(centerX.toFixed(2)),
      y: Number(centerY.toFixed(2)),
      strength: confidence,
      size: Math.round(20 + confidence * 10),
    }];
  });
}
