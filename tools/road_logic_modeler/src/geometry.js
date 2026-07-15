(function () {
  "use strict";

  function clamp(value, min, max) {
    return Math.min(max, Math.max(min, value));
  }

  function distance(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function angle(a, b) {
    return Math.atan2(b.y - a.y, b.x - a.x);
  }

  function sideFromAngle(rad) {
    const deg = (rad * 180 / Math.PI + 360) % 360;
    if (deg >= 315 || deg < 45) return "east";
    if (deg >= 45 && deg < 135) return "south";
    if (deg >= 135 && deg < 225) return "west";
    return "north";
  }

  function snapPoint(point, step) {
    return {
      x: Math.round(point.x / step) * step,
      y: Math.round(point.y / step) * step
    };
  }

  function distanceToSegment(point, a, b) {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const lenSq = dx * dx + dy * dy;
    if (!lenSq) return distance(point, a);
    const t = clamp(((point.x - a.x) * dx + (point.y - a.y) * dy) / lenSq, 0, 1);
    return distance(point, { x: a.x + dx * t, y: a.y + dy * t });
  }

  function distanceToPolyline(point, points) {
    let best = Infinity;
    for (let i = 0; i < points.length - 1; i += 1) {
      best = Math.min(best, distanceToSegment(point, points[i], points[i + 1]));
    }
    return best;
  }

  function pointOnPolyline(points, ratio) {
    if (!points.length) return { x: 0, y: 0 };
    if (points.length === 1) return { x: points[0].x, y: points[0].y };
    const lengths = [];
    let total = 0;
    for (let i = 0; i < points.length - 1; i += 1) {
      const len = distance(points[i], points[i + 1]);
      lengths.push(len);
      total += len;
    }
    let target = total * clamp(ratio, 0, 1);
    for (let i = 0; i < lengths.length; i += 1) {
      if (target <= lengths[i]) {
        const t = lengths[i] ? target / lengths[i] : 0;
        return {
          x: points[i].x + (points[i + 1].x - points[i].x) * t,
          y: points[i].y + (points[i + 1].y - points[i].y) * t
        };
      }
      target -= lengths[i];
    }
    return { ...points[points.length - 1] };
  }

  function segmentAt(points, ratio) {
    const p = pointOnPolyline(points, ratio);
    let best = null;
    let bestDist = Infinity;
    for (let i = 0; i < points.length - 1; i += 1) {
      const d = distanceToSegment(p, points[i], points[i + 1]);
      if (d < bestDist) {
        bestDist = d;
        best = { a: points[i], b: points[i + 1] };
      }
    }
    return best;
  }

  function offsetPolyline(points, offset) {
    if (!offset || points.length < 2) return points.map((p) => ({ x: p.x, y: p.y }));
    return points.map((p, i) => {
      const prev = points[Math.max(0, i - 1)];
      const next = points[Math.min(points.length - 1, i + 1)];
      const dx = next.x - prev.x;
      const dy = next.y - prev.y;
      const len = Math.hypot(dx, dy) || 1;
      return { x: p.x + (-dy / len) * offset, y: p.y + (dx / len) * offset };
    });
  }

  function rectBounds(rect) {
    return {
      left: rect.x - rect.width / 2,
      right: rect.x + rect.width / 2,
      top: rect.y - rect.height / 2,
      bottom: rect.y + rect.height / 2
    };
  }

  function nearestRectEdge(point, rect) {
    const b = rectBounds(rect);
    const x = clamp(point.x, b.left, b.right);
    const y = clamp(point.y, b.top, b.bottom);
    const candidates = [
      { side: "north", x, y: b.top },
      { side: "south", x, y: b.bottom },
      { side: "west", x: b.left, y },
      { side: "east", x: b.right, y }
    ];
    return candidates.reduce((best, item) => {
      const d = distance(point, item);
      return d < best.distance ? { ...item, distance: d } : best;
    }, { ...candidates[0], distance: Infinity });
  }

  function cellCenter(cell, gridSize) {
    return { x: (cell[0] + 0.5) * gridSize, y: (cell[1] + 0.5) * gridSize };
  }

  function cameraPoseFromPoints(origin, endpoint, minRange) {
    const dx = endpoint.x - origin.x;
    const dy = endpoint.y - origin.y;
    return {
      direction: (Math.atan2(dy, dx) * 180 / Math.PI + 360) % 360,
      range: Math.max(Number(minRange) || 0, Math.hypot(dx, dy))
    };
  }

  function cameraRangePoint(camera) {
    const rad = Number(camera.direction || 0) * Math.PI / 180;
    const range = Math.max(0, Number(camera.range) || 0);
    return { x: camera.x + Math.cos(rad) * range, y: camera.y + Math.sin(rad) * range };
  }

  window.RoadLogicModeler = window.RoadLogicModeler || {};
  window.RoadLogicModeler.geometry = {
    clamp,
    distance,
    angle,
    sideFromAngle,
    snapPoint,
    distanceToSegment,
    distanceToPolyline,
    pointOnPolyline,
    segmentAt,
    offsetPolyline,
    rectBounds,
    nearestRectEdge,
    cellCenter,
    cameraPoseFromPoints,
    cameraRangePoint
  };
})();
