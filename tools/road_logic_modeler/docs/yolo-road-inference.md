# YOLO To Road Graph Inference

## Goal

Convert vehicle detections from each RTSP camera into ground-plane positions, lane observations, and time-ordered trajectories. The fixed inputs are:

- `analysis/baseline/road_logic_model (4).road-lane.v1.json`
- `analysis/baseline/road_logic_model (4).camera-mapping.v1.json`

Do not use `lane-vector.json` for the first pass. It contains experimental junction-turn inference and is not a ground truth traffic rule set.

## Per-frame Pipeline

1. Read one frame from an RTSP stream.
2. Run YOLO vehicle detection. Keep `car`, `bus`, `truck`, `motorcycle`, and other required classes.
3. Associate detections across frames with a tracker such as ByteTrack. The tracker produces a local `trackId`.
4. Use the bottom-center of each bounding box as the road contact point:

   ```text
   contactPixel = ((x1 + x2) / 2, y2)
   ```

   The box center is not suitable because it moves with vehicle height and camera perspective.
5. Project `contactPixel` from image coordinates to the model ground plane.
6. Assign the resulting world point to a rendered lane, building, or free space using the baseline lane geometry.
7. Append the observation to the track and analyze the ordered lane sequence.

## Image To Ground Projection

Each camera mapping record contains pairs of `imagePosition` and `worldPoint`.

For a camera with at least four well-spaced, non-collinear road-plane points, fit a homography with RANSAC:

```text
[worldX, worldY, 1]^T ~ H * [imageX, imageY, 1]^T
```

Ignore `worldPoint.height` for this first ground-plane transform. It is an editor elevation value, not a vehicle height estimate.

### Current Readiness

| Camera | Mapping points | Initial projection status |
| --- | ---: | --- |
| cam_1 | 4 | Validate point distribution, then fit |
| cam_2 | 2 | Add at least 2 more road points |
| cam_3 | 4 | Validate point distribution, then fit |
| cam_4 | 2 | Add at least 2 more road points |
| cam_5 | 10 | Ready for validation |
| cam_6 | 6 | Ready for validation |
| cam_7 | 9 | Ready for validation |
| cam_8 | 5 | Ready for validation |
| cam_9 | 4 | Validate point distribution, then fit |
| cam_10 | 10 | Ready for validation |
| cam_11 | 2 | Add at least 2 more road points |
| cam_12 | 10 | Ready for validation |

Four points are the mathematical minimum. Six or more points distributed across the usable road region are preferred. Reject or flag a camera when holdout reprojection error exceeds one model grid cell (20 world units) or the points are nearly collinear.

For `cam_2`, `cam_4`, and `cam_11`, do not fabricate a 2D mapping from two points. They may be used only for image-space tracking until more calibration points are added.

## World Point To Lane

For each projected point:

1. Calculate distance to every `lanes[].geometry.renderPath`.
2. A point is inside a lane when distance is no greater than half of `lanes[].geometry.width`.
3. If exactly one lane contains the point, set `laneStatus = single_lane`.
4. If multiple lanes contain it near a junction, retain all candidate IDs as `ambiguous_lane_band`.
5. Resolve ambiguous observations with the track's previous lane and projected motion, not merely nearest distance.

The model already has offset rendering paths for parallel lanes. Use these paths rather than the shared endpoint center line.

## Direction And Graph Analysis

Each lane contains:

- `traffic.sourceNodeId` and `traffic.targetNodeId`: legal travel direction.
- `traffic.direction`: original editor direction (`1-2` or `2-1`).
- `traffic.sourceArrow` and `traffic.targetArrow`: observed lane arrow markings.
- `markings.leftBoundary` and `markings.rightBoundary`: line styles.

For every tracked world point, project the track displacement onto the nearest lane tangent:

```text
signedProgress = dot(worldPosition[t] - worldPosition[t-1], laneTangent)
```

- Positive progress follows the lane's legal direction.
- Sustained negative progress indicates a possible reverse-direction event.
- A transition between adjacent lane bands can be compared with the crossed lane boundary style. Crossing a `solid` boundary is a candidate event; a `dashed` boundary is normally allowed.
- Do not classify an event on one frame. Require a stable world position and a minimum sequence duration/distance.

At this stage, use `road-lane.v1.json` node adjacency only to describe road context. Do not infer turn legality across a complex junction until explicit `incoming lane -> outgoing lane` rules have been reviewed and saved.

## Observation Output

Write one record per tracked detection. Keep raw and derived values together for auditability.

```json
{
  "cameraId": "cam_5",
  "timestampMs": 1730000000000,
  "trackId": "cam_5:42",
  "class": "car",
  "confidence": 0.91,
  "box": {"x1": 620, "y1": 390, "x2": 780, "y2": 620},
  "contactPixel": {"x": 700, "y": 620},
  "worldPoint": {"x": 640.4, "y": 501.8},
  "projection": {"method": "homography", "reprojectionError": 7.3},
  "lane": {
    "status": "single_lane",
    "laneId": "lane_97",
    "candidateLaneIds": ["lane_97"],
    "signedProgress": 12.6
  }
}
```

Keep a separate event record, linked to the observation IDs, for reverse travel, boundary crossing, stopped vehicle, or other rules. This prevents a model threshold change from destroying the original detection evidence.

## Validation Order

1. Select one ready camera with 6 or more points, preferably `cam_5`, `cam_7`, `cam_10`, or `cam_12`.
2. Draw projected contact points over the road model and measure reprojection error using held-out calibration points.
3. Run YOLO and tracking on a short recording.
4. Compare lane assignments with the camera image manually.
5. Only after stable lane assignment, add direction and boundary-crossing analysis.
6. Add the remaining cameras after their calibration quality is verified.

## Traffic Analysis Runner

After projection and tracking, write one JSON object per line using the observation format above. Run:

```powershell
python tools/road_logic_modeler/traffic_analysis.py `
  --road "tools/road_logic_modeler/analysis/baseline/road_logic_model (4).road-lane.v1.json" `
  --observations observations.jsonl `
  --output-dir traffic-output
```

The runner produces:

- `traffic-analysis.v1.json`: lane flow, annotated observations, and candidate events.
- `traffic-heatmap.png`: world-grid heatmap drawn over the lane model.

Current candidate event rules are `reverse_direction_candidate`, `solid_boundary_crossing_candidate`, and `stopped_on_lane_candidate`. They are review signals, not final enforcement results.

## Reproducible Node Test

`examples/node_2_traffic_observations.sample.jsonl` uses real model coordinates around `node_2`. It includes one normal track, one reverse track, one solid-boundary crossing, and one stationary vehicle.

```powershell
python tools/road_logic_modeler/traffic_analysis.py `
  --road "tools/road_logic_modeler/analysis/baseline/road_logic_model (4).road-lane.v1.json" `
  --observations tools/road_logic_modeler/examples/node_2_traffic_observations.sample.jsonl `
  --output-dir tools/road_logic_modeler/analysis/sample-traffic-run
```

Expected result: 11 observations, 4 tracks, and 3 candidate events. This is a regression fixture for the analysis layer; it does not represent real traffic video.

## Limits

- A planar homography is valid only for road surfaces close to one plane. Bridges, ramps, and large elevation changes require separate calibration regions or a 3D camera model.
- Detection-box bottom centers can be wrong during occlusion, truncation, or heavy shadow. Track smoothing and confidence gates are required.
- Cross-camera identity association is a later step. Initial tests should use a separate tracker namespace for each camera.
