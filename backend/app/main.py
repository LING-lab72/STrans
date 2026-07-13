from __future__ import annotations

from datetime import datetime
from io import BytesIO
import hashlib
import json
import threading
import time
from zipfile import ZIP_DEFLATED, ZipFile

import cv2
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse

from app.schemas.dashboard import (
    AlgorithmServiceConfig,
    AnalysisResult,
    AnalysisPushRequest,
    AuthRequest,
    AuthResponse,
    AuthUser,
    DetectionConfig,
    GateDecision,
    GateDecisionRequest,
    IntelligenceReportConfigUpdate,
    IntelligenceReportGenerateRequest,
    IncidentUpdateRequest,
    PasswordChangeRequest,
    PasswordResetRequest,
    RegisterRequest,
    TrafficStats,
    WhitelistCreateRequest,
    UserAdminUpdateRequest,
)
from app.schemas.video import CameraCreateRequest, CameraSource, CameraUpdateRequest, RoadMaskSnapshot, StartAllRequest, VideoStartRequest, VideoStatus
from app.services.algorithm_client import AlgorithmClient
from app.services.analysis_store import AnalysisStore
from app.services.adaptive_scheduler import adaptive_model_scheduler
from app.services.auth_store import auth_store
from app.services.camera_hub import CameraHub
from app.services.local_model import LocalModelService
from app.services.intelligence_report import intelligence_report_service
from app.services.road_anomaly import road_anomaly_service
from app.services.road_logic import road_logic_service
from app.services.road_mask import road_mask_service
from app.services.system_monitor import system_monitor
from app.services.weather import beijing_weather_service
from app.services.whitelist import decide_plate, whitelist_store


app = FastAPI(title="STrans Camera Gateway", version="0.4.0")
camera_hub = CameraHub()
algorithm_client = AlgorithmClient()
analysis_store = AnalysisStore()
local_model = LocalModelService()
last_stream_history_save: dict[str, float] = {}
model_stream_lock = threading.Lock()
model_stream_generation = 0

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _annotate_evidence_image(image: bytes | None, analysis: dict) -> bytes | None:
    if not image:
        return None
    frame = cv2.imdecode(np.frombuffer(image, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return None
    for detection in analysis.get("detections") or []:
        bbox = detection.get("bbox") or []
        if len(bbox) != 4:
            continue
        x1, y1, x2, y2 = [int(round(float(value))) for value in bbox]
        label = str(detection.get("class_name") or "target")
        if detection.get("plate"):
            label += f" {detection['plate']}"
        color = (22, 163, 74) if detection.get("whitelist_status") is True else (38, 38, 220)
        if "obstacle" in label or "pedestrian" in label:
            color = (32, 156, 245)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3)
        cv2.putText(frame, label, (x1, max(24, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return encoded.tobytes() if ok else None


def _ensure_camera(camera_id: str) -> None:
    if camera_id not in {camera.camera_id for camera in camera_hub.list_sources()}:
        raise HTTPException(status_code=404, detail=f"Camera not found: {camera_id}")


def _report_context(camera_id: str | None) -> dict:
    """Build a compact, factual snapshot for the report model."""
    result = algorithm_client.latest_result
    active_camera_id = camera_id or result.camera_id or camera_hub.current_camera_id
    camera = next((item for item in camera_hub.list_sources() if item.camera_id == active_camera_id), None)
    stats = result.traffic_stats.model_dump()
    detections = [
        {
            "class": item.class_name,
            "confidence": round(float(item.confidence), 3),
            "track_id": item.track_id,
            "plate": item.plate,
            "whitelist_status": item.whitelist_status,
            "speed_cm_s": item.speed_cm_s,
        }
        for item in result.detections[:30]
    ]
    events = [
        {"type": item.type, "severity": item.severity, "description": item.description, "camera_id": item.camera_id}
        for item in result.events[:20]
    ]
    history = analysis_store.list_records(limit=12, camera_id=active_camera_id)
    return {
        "generated_at": _now(),
        "camera_id": active_camera_id,
        "camera_name": camera.name if camera else active_camera_id,
        "current_result_timestamp": result.timestamp,
        "model": result.model_id,
        "inference_ms": result.inference_ms,
        "traffic_stats": stats,
        "detections": detections,
        "events": events,
        "road_heatmap": road_logic_service.heatmap_snapshot(active_camera_id).get("lane_stats", {}),
        "weather": beijing_weather_service.snapshot(),
        "recent_history": history,
        "data_note": "数据来自当前实时分析结果和最近 12 条已持久化检测记录；检测结果可能受到视角、遮挡、模型置信度影响。",
    }


def _anomaly_only_result(result: AnalysisResult) -> AnalysisResult:
    """Keep anomaly mode independent from vehicle analytics and gate workflows."""
    anomaly_detection_names = {"pedestrian", "road_obstacle_candidate"}
    anomaly_event_types = {"road_pedestrian", "road_obstacle", "road_damage"}
    filtered = result.model_copy(deep=True)
    filtered.detections = [
        item
        for item in result.detections
        if (
            (item.class_name == "pedestrian" and float(item.confidence) >= 0.55)
            or item.class_name == "road_obstacle_candidate"
            or str(item.class_name).startswith("road_damage:")
        )
    ]
    filtered.events = [item for item in result.events if item.type in anomaly_event_types]
    filtered.traffic_stats = TrafficStats(congestion_level="unknown")
    raw = dict(filtered.raw or {})
    raw["task_mode"] = "road_anomaly"
    raw["vehicle_analytics_excluded"] = True
    filtered.raw = raw
    return filtered


def _token_from_header(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    return authorization.strip()


def current_user(authorization: str | None = Header(default=None)) -> dict:
    user = auth_store.get_user_by_token(_token_from_header(authorization))
    if not user:
        raise HTTPException(status_code=401, detail="Please login first.")
    return user


def current_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Administrator permission required.")
    return user


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "camera-gateway"}


@app.get("/api/system/resources")
def system_resources():
    return system_monitor.snapshot(algorithm_client.latest_result.inference_ms)


@app.get("/api/weather/beijing")
def beijing_weather():
    return beijing_weather_service.snapshot()


@app.get("/api/auth/captcha")
def auth_captcha():
    return auth_store.new_captcha()


@app.post("/api/auth/register", response_model=AuthResponse)
def auth_register(req: RegisterRequest) -> AuthResponse:
    if not auth_store.verify_captcha(req.captcha_id, req.captcha_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    try:
        user = auth_store.create_user(req.username, req.password, role="user")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    token = auth_store.create_session(user["id"])
    return AuthResponse(token=token, user=AuthUser(**user))


@app.post("/api/auth/login", response_model=AuthResponse)
def auth_login(req: AuthRequest) -> AuthResponse:
    if not auth_store.verify_captcha(req.captcha_id, req.captcha_code):
        raise HTTPException(status_code=400, detail="验证码错误或已过期")
    user = auth_store.authenticate(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    token = auth_store.create_session(user["id"])
    return AuthResponse(token=token, user=AuthUser(**user))


@app.get("/api/auth/me", response_model=AuthUser)
def auth_me(user: dict = Depends(current_user)) -> AuthUser:
    return AuthUser(**user)


@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = Header(default=None)):
    auth_store.delete_session(_token_from_header(authorization))
    return {"ok": True}


@app.put("/api/auth/password")
def change_own_password(req: PasswordChangeRequest, user: dict = Depends(current_user)):
    try:
        auth_store.change_password(user["id"], req.old_password, req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_store.add_audit(user["username"], "change_password", user["username"], "用户修改自己的登录密码")
    return {"ok": True, "reauth_required": True}


@app.get("/api/admin/users")
def list_system_users(user: dict = Depends(current_admin)):
    return {"items": auth_store.list_users()}


@app.put("/api/admin/users/{user_id}")
def update_system_user(user_id: int, req: UserAdminUpdateRequest, user: dict = Depends(current_admin)):
    if user_id == user["id"] and req.enabled is False:
        raise HTTPException(status_code=400, detail="不能禁用当前登录账号")
    try:
        updated = auth_store.update_user(user_id, role=req.role, enabled=req.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_store.add_audit(user["username"], "update_user", updated.get("username", str(user_id)), req.model_dump_json(exclude_none=True))
    return updated


@app.put("/api/admin/users/{user_id}/password")
def reset_system_user_password(user_id: int, req: PasswordResetRequest, user: dict = Depends(current_admin)):
    try:
        auth_store.reset_password(user_id, req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_store.add_audit(user["username"], "reset_password", str(user_id), "管理员重置用户密码")
    return {"ok": True}


@app.delete("/api/admin/users/{user_id}")
def delete_system_user(user_id: int, user: dict = Depends(current_admin)):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录账号")
    try:
        auth_store.delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_store.add_audit(user["username"], "delete_user", str(user_id), "管理员删除用户")
    return {"ok": True}


@app.get("/api/admin/audit")
def list_audit_logs(limit: int = Query(default=100, ge=1, le=500), user: dict = Depends(current_admin)):
    return {"items": auth_store.list_audit(limit)}


@app.get("/api/cameras", response_model=list[CameraSource])
def list_cameras(user: dict = Depends(current_user)) -> list[CameraSource]:
    return camera_hub.list_sources()


@app.post("/api/cameras", response_model=CameraSource)
def add_camera(req: CameraCreateRequest, user: dict = Depends(current_admin)) -> CameraSource:
    camera = camera_hub.add_source(req)
    auth_store.add_audit(user["username"], "create_camera", camera.camera_id, camera.name)
    return camera


@app.put("/api/cameras/{camera_id}", response_model=CameraSource)
def update_camera(camera_id: str, req: CameraUpdateRequest, user: dict = Depends(current_admin)) -> CameraSource:
    try:
        camera = camera_hub.update_source(camera_id, req)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="摄像头不存在") from exc
    auth_store.add_audit(user["username"], "update_camera", camera_id, req.model_dump_json(exclude_none=True))
    return camera


@app.delete("/api/cameras/{camera_id}")
def delete_camera(camera_id: str, user: dict = Depends(current_admin)):
    try:
        camera_hub.delete_source(camera_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="摄像头不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_store.add_audit(user["username"], "delete_camera", camera_id, "删除自定义摄像头")
    return {"ok": True}


@app.post("/api/cameras/{camera_id}/test")
def test_camera(camera_id: str, user: dict = Depends(current_admin)):
    try:
        return camera_hub.test_source(camera_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="摄像头不存在") from exc


@app.post("/api/cameras/{camera_id}/start", response_model=VideoStatus)
def start_camera(camera_id: str, user: dict = Depends(current_user)) -> VideoStatus:
    _ensure_camera(camera_id)
    return camera_hub.start(camera_id)


@app.post("/api/cameras/{camera_id}/stop", response_model=VideoStatus)
def stop_camera(camera_id: str, user: dict = Depends(current_user)) -> VideoStatus:
    _ensure_camera(camera_id)
    return camera_hub.stop(camera_id)


@app.post("/api/cameras/start-all")
def start_all_cameras(req: StartAllRequest, user: dict = Depends(current_admin)):
    camera_ids = req.camera_ids or [camera.camera_id for camera in camera_hub.list_sources() if camera.type == "sandtable"]
    results = []
    known_ids = {camera.camera_id for camera in camera_hub.list_sources()}
    for camera_id in camera_ids:
        if camera_id in known_ids:
            results.append({"camera_id": camera_id, "status": camera_hub.start(camera_id)})
    return {"items": results}


@app.post("/api/cameras/stop-all")
def stop_all_cameras(user: dict = Depends(current_admin)):
    return {"items": camera_hub.stop_all()}


@app.get("/api/cameras/status")
def camera_status_all():
    return {"items": camera_hub.status_all()}


@app.get("/api/cameras/{camera_id}/status", response_model=VideoStatus)
def camera_status(camera_id: str) -> VideoStatus:
    _ensure_camera(camera_id)
    return camera_hub.status(camera_id)


@app.get("/api/cameras/{camera_id}/mjpeg")
def camera_mjpeg(camera_id: str) -> StreamingResponse:
    _ensure_camera(camera_id)
    return StreamingResponse(
        camera_hub.mjpeg_frames(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/cameras/{camera_id}/model-mjpeg")
def camera_model_mjpeg(
    camera_id: str,
    model_name: str = Query(default="auto", pattern="^(auto|visdrone|fallback)$"),
    task_mode: str = Query(default="traffic", pattern="^(traffic|road_anomaly)$"),
) -> StreamingResponse:
    global model_stream_generation
    _ensure_camera(camera_id)
    config = algorithm_client.detection_config
    with model_stream_lock:
        model_stream_generation += 1
        stream_generation = model_stream_generation

    def is_current_stream() -> bool:
        with model_stream_lock:
            return stream_generation == model_stream_generation

    def handle_traffic_result(result: AnalysisResult, source_jpeg: bytes) -> None:
        if not is_current_stream():
            return
        active_policy = next(
            (item for item in adaptive_model_scheduler.snapshot()["active"] if item.get("camera_id") == camera_id),
            None,
        )
        result.raw = {**(result.raw or {}), "adaptive_scheduler": active_policy}
        result = road_logic_service.enrich(result)
        algorithm_client.push_result(result)
        now = time.monotonic()
        if now - last_stream_history_save.get(camera_id, 0) >= 5.0:
            analysis_store.save(result, source_jpeg=source_jpeg)
            last_stream_history_save[camera_id] = now

    def anomaly_frames():
        # The base model is used only to avoid mistaking moving road users for
        # debris. Its vehicle output is discarded before both annotation and
        # dashboard aggregation.
        road_anomaly_service.reset(camera_id)
        while is_current_stream():
            cycle_started = time.perf_counter()
            source_jpeg = camera_hub.latest_jpeg(camera_id)
            if source_jpeg is None:
                time.sleep(0.05)
                continue
            # A still JPG/PNG has no temporal frame difference. Enable the
            # image-specific static-scene candidate path only for that source
            # type; live cameras keep the stricter multi-frame path so lane
            # markings and lighting changes cannot become obstacles.
            is_static_image = camera_hub.status(camera_id).is_static_image
            policy = adaptive_model_scheduler.choose(
                camera_id,
                task_mode,
                model_name,
                config.confidence,
                config.inference_size,
                config.detection_interval_ms,
                algorithm_client.latest_result.inference_ms,
                is_static_image,
            )
            base_result, _ = local_model.infer_jpeg(
                camera_id,
                source_jpeg,
                model_name=policy["model_name"],
                conf=policy["confidence"],
                imgsz=policy["inference_size"],
                annotate=False,
                stream_mode=True,
                include_people=True,
            )
            anomaly_result = road_anomaly_service.analyze_jpeg(
                camera_id,
                source_jpeg,
                base_result,
                include_damage_model=False,
                # Fixed sandtable cameras may already contain an obstacle when
                # anomaly mode starts, so frame differencing alone is not
                # sufficient. The static path is ROI- and appearance-gated.
                include_static_scene=True,
            )
            anomaly_result = _anomaly_only_result(anomaly_result)
            anomaly_result.raw = {**(anomaly_result.raw or {}), "adaptive_scheduler": policy}
            algorithm_client.push_result(anomaly_result)
            now = time.monotonic()
            if now - last_stream_history_save.get(camera_id, 0) >= 5.0:
                analysis_store.save(anomaly_result, source_jpeg=source_jpeg)
                last_stream_history_save[camera_id] = now
            annotated = road_anomaly_service.annotate_jpeg(source_jpeg, anomaly_result)
            if annotated is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-cache\r\n\r\n" + annotated + b"\r\n"
                )
            elapsed = time.perf_counter() - cycle_started
            time.sleep(max(0.0, max(0.03, policy["detection_interval_ms"] / 1000) - elapsed))

    if task_mode == "road_anomaly":
        return StreamingResponse(
            anomaly_frames(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache"},
        )

    return StreamingResponse(
        local_model.annotated_mjpeg_frames(
            camera_id,
            lambda: camera_hub.latest_jpeg(camera_id),
            model_name=model_name,
            conf=config.confidence,
            imgsz=config.inference_size,
            sleep_seconds=max(0.03, config.detection_interval_ms / 1000),
            on_result=handle_traffic_result,
            should_continue=is_current_stream,
            policy_provider=lambda: adaptive_model_scheduler.choose(
                camera_id,
                task_mode,
                model_name,
                config.confidence,
                config.inference_size,
                config.detection_interval_ms,
                algorithm_client.latest_result.inference_ms,
                camera_hub.status(camera_id).is_static_image,
            ),
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/api/video/start", response_model=CameraSource)
def start_manual_video(req: VideoStartRequest) -> CameraSource:
    return camera_hub.start_custom(req.source.strip(), req.name, req.location)


@app.post("/api/video/stop")
def stop_current_video():
    return camera_hub.stop(camera_hub.current_camera_id)


@app.get("/api/video/status", response_model=VideoStatus)
def current_video_status() -> VideoStatus:
    return camera_hub.status(camera_hub.current_camera_id)


@app.get("/api/video/mjpeg")
def current_video_mjpeg() -> StreamingResponse:
    return camera_mjpeg(camera_hub.current_camera_id)


@app.get("/api/algorithm/config")
def get_algorithm_config():
    return algorithm_client.get_state()


@app.put("/api/algorithm/config")
def update_algorithm_config(req: AlgorithmServiceConfig, user: dict = Depends(current_admin)):
    return algorithm_client.update_config(req)


@app.get("/api/algorithm/health")
async def algorithm_health():
    return await algorithm_client.health()


@app.post("/api/algorithm/infer/{camera_id}")
async def infer_camera_frame(camera_id: str):
    _ensure_camera(camera_id)
    jpeg = camera_hub.latest_jpeg(camera_id)
    if algorithm_client.config.enabled and algorithm_client.config.base_url:
        result = await algorithm_client.infer_frame(camera_id, jpeg)
    elif jpeg is None:
        result = algorithm_client.push_result(
            AnalysisResult(timestamp=_now(), camera_id=camera_id, error="No frame available for this camera. Start the camera stream first.")
        )
    else:
        result, _ = local_model.infer_jpeg(camera_id, jpeg, model_name="auto", annotate=False, include_people=True)
        result = road_anomaly_service.analyze_jpeg(camera_id, jpeg, result, include_damage_model=True)
    if not result.error:
        result = road_logic_service.enrich(result)
    algorithm_client.push_result(result)
    analysis_store.save(result)
    return result


@app.post("/api/algorithm/results")
def push_algorithm_result(req: AnalysisPushRequest):
    result = road_logic_service.enrich(req) if not req.error else req
    result = algorithm_client.push_result(result)
    analysis_store.save(result)
    return result


@app.get("/api/analysis/latest")
def latest_analysis():
    return algorithm_client.latest_result


@app.get("/api/cameras/{camera_id}/road-mask", response_model=RoadMaskSnapshot)
def camera_road_mask(camera_id: str, user: dict = Depends(current_user)) -> RoadMaskSnapshot:
    _ensure_camera(camera_id)
    try:
        snapshot = road_mask_service.snapshot(camera_id, camera_hub.latest_jpeg(camera_id))
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail="Road mask model is unavailable. Check the server model deployment.") from error
    if snapshot["status"] != "ready":
        raise HTTPException(status_code=409, detail=snapshot["error"])
    return RoadMaskSnapshot(**snapshot)


@app.get("/api/road-mask/health")
def road_mask_health(user: dict = Depends(current_admin)):
    return road_mask_service.health()


@app.get("/api/analysis/events")
def analysis_events():
    return algorithm_client.events


@app.get("/api/history")
def analysis_history(limit: int = Query(default=30, ge=1, le=500), camera_id: str | None = None, user: dict = Depends(current_user)):
    return {
        "items": analysis_store.list_records(limit=limit, camera_id=camera_id),
        "total": analysis_store.count_records(camera_id=camera_id),
    }


@app.get("/api/history/export")
def export_analysis_history(format: str = Query(default="csv", pattern="^(csv|json)$"), limit: int = Query(default=1000, ge=1, le=5000), user: dict = Depends(current_user)):
    if format == "json":
        return Response(
            content=analysis_store.export_json(limit=limit),
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="traffic-analysis-history.json"'},
        )
    return Response(
        content=analysis_store.export_csv(limit=limit),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="traffic-analysis-history.csv"'},
    )


@app.delete("/api/history/{record_id}")
def delete_analysis_history(record_id: int, user: dict = Depends(current_admin)):
    if not analysis_store.delete_record(record_id):
        raise HTTPException(status_code=404, detail="历史记录不存在")
    auth_store.add_audit(user["username"], "delete_history", str(record_id), "删除检测历史记录")
    return {"ok": True}


@app.delete("/api/history")
def purge_analysis_history(before: str | None = None, user: dict = Depends(current_admin)):
    removed = analysis_store.purge_records(before=before)
    auth_store.add_audit(user["username"], "purge_history", before or "all", f"删除 {removed} 条检测历史")
    return {"ok": True, "removed": removed}


@app.get("/api/incidents")
def list_incidents(status: str | None = None, limit: int = Query(default=100, ge=1, le=500), user: dict = Depends(current_user)):
    return {"items": analysis_store.list_incidents(limit=limit, status=status)}


@app.get("/api/incidents/{event_id}/evidence")
def download_incident_evidence(event_id: str, user: dict = Depends(current_user)):
    evidence = analysis_store.get_incident_evidence(event_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="告警记录不存在")
    incident = evidence["incident"]
    image = evidence["image"]
    if image is None and incident.get("camera_id"):
        image = camera_hub.latest_jpeg(incident["camera_id"])
        if image:
            evidence["image_sha256"] = hashlib.sha256(image).hexdigest()
    annotated_image = _annotate_evidence_image(image, evidence["analysis"])
    manifest = {
        "package_version": "1.1",
        "generated_at": _now(),
        "generated_by": user["username"],
        "incident": incident,
        "image_sha256": evidence["image_sha256"],
        "annotated_image_sha256": hashlib.sha256(annotated_image).hexdigest() if annotated_image else None,
        "adaptive_scheduler": adaptive_model_scheduler.snapshot(),
        "chain_note": "告警、检测结果、处置记录与原始帧按 event_id 关联。SHA-256 用于验证截图未被替换。",
    }
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("analysis-result.json", json.dumps(evidence["analysis"], ensure_ascii=False, indent=2))
        archive.writestr("incident.json", json.dumps(incident, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", "STrans 告警证据包\n包含告警元数据、关联检测结果、原始帧及截图 SHA-256 校验值。\n")
        if image:
            archive.writestr("evidence-frame-original.jpg", image)
        if annotated_image:
            archive.writestr("evidence-frame-annotated.jpg", annotated_image)
    auth_store.add_audit(user["username"], "export_evidence", event_id, "导出告警证据包")
    return Response(
        content=output.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="evidence-{event_id}.zip"'},
    )


@app.put("/api/incidents/{event_id}")
def update_incident(event_id: str, req: IncidentUpdateRequest, user: dict = Depends(current_user)):
    try:
        incident = analysis_store.update_incident(event_id, req.status, user["username"], req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    auth_store.add_audit(user["username"], "handle_incident", event_id, f"{req.status}: {req.note}")
    return incident


@app.get("/api/model-scheduler")
def model_scheduler_state(user: dict = Depends(current_user)):
    return adaptive_model_scheduler.snapshot()


@app.put("/api/model-scheduler")
def update_model_scheduler(enabled: bool, user: dict = Depends(current_admin)):
    state = adaptive_model_scheduler.configure(enabled)
    auth_store.add_audit(user["username"], "configure_scheduler", "adaptive_model_scheduler", f"enabled={enabled}")
    return state


@app.get("/api/intelligence/config")
def intelligence_config(user: dict = Depends(current_admin)):
    return intelligence_report_service.get_config()


@app.put("/api/intelligence/config")
def update_intelligence_config(req: IntelligenceReportConfigUpdate, user: dict = Depends(current_admin)):
    try:
        return intelligence_report_service.update_config(req.api_base, req.model, req.api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/intelligence/reports")
def intelligence_reports(limit: int = Query(default=30, ge=1, le=100), user: dict = Depends(current_user)):
    return {"items": intelligence_report_service.list_reports(limit)}


@app.post("/api/intelligence/reports")
def generate_intelligence_report(req: IntelligenceReportGenerateRequest, user: dict = Depends(current_admin)):
    try:
        return intelligence_report_service.generate(_report_context(req.camera_id), user.get("username"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.delete("/api/intelligence/reports/{report_id}")
def delete_intelligence_report(report_id: int, user: dict = Depends(current_admin)):
    if not intelligence_report_service.delete_report(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"removed": True, "id": report_id}


@app.get("/api/config/threshold")
def get_detection_config():
    return algorithm_client.detection_config


@app.put("/api/config/threshold")
def update_detection_config(req: DetectionConfig, user: dict = Depends(current_admin)):
    config = algorithm_client.update_detection_config(req)
    auth_store.add_audit(user["username"], "update_model_config", "detection", req.model_dump_json())
    return config


@app.get("/api/dashboard")
def dashboard_snapshot():
    return {
        "algorithm": algorithm_client.get_state(),
        "current_camera_id": camera_hub.current_camera_id,
        "latest_analysis": algorithm_client.latest_result,
        "events": algorithm_client.events[:30],
        "config": algorithm_client.detection_config,
        "cameras": camera_hub.list_sources(),
        "camera_status": camera_hub.status_all(),
        "history": analysis_store.list_records(limit=10),
    }


@app.get("/api/models")
def model_gateway_info():
    return {
        "current_model": algorithm_client.latest_result.model_id,
        "mode": "local_sandtable_model" if not algorithm_client.config.enabled else "remote_algorithm_service",
        "message": "Local sandtable model is available. Remote teammate algorithm service can still be configured.",
        "algorithm": algorithm_client.get_state(),
        "local": local_model.health(),
        "road_anomaly": road_anomaly_service.health(),
        "road_logic": road_logic_service.model_snapshot(),
    }


@app.get("/api/road-model")
def road_model():
    return road_logic_service.model_snapshot()


@app.get("/api/road-model/heatmap")
def road_model_heatmap(camera_id: str | None = None):
    return road_logic_service.heatmap_snapshot(camera_id)


@app.get("/api/road-anomaly/health")
def road_anomaly_health():
    return road_anomaly_service.health()


@app.post("/api/road-anomaly/reset")
def road_anomaly_reset(camera_id: str | None = None):
    road_anomaly_service.reset(camera_id)
    return {"ok": True, "camera_id": camera_id}


@app.post("/api/road-anomaly/analyze/{camera_id}", response_model=AnalysisResult)
def analyze_road_anomaly(camera_id: str, include_damage_model: bool = Query(default=True)):
    _ensure_camera(camera_id)
    jpeg = camera_hub.latest_jpeg(camera_id)
    if jpeg is None:
        result = AnalysisResult(timestamp=_now(), camera_id=camera_id, error="No frame available for this camera. Start the camera stream first.")
    else:
        base, _ = local_model.infer_jpeg(camera_id, jpeg, model_name="auto", annotate=False, include_people=True)
        # Imported JPG/PNG files have no temporal change. Let the anomaly
        # service use its image-specific candidate path for them, matching the
        # road-anomaly MJPEG stream; live cameras remain multi-frame only.
        result = road_anomaly_service.analyze_jpeg(
            camera_id,
            jpeg,
            base,
            include_damage_model=include_damage_model,
            include_static_scene=True,
        )
        result = _anomaly_only_result(result)
    algorithm_client.push_result(result)
    analysis_store.save(result)
    return result


@app.put("/api/models/current")
def model_selection_disabled(user: dict = Depends(current_admin)):
    return {
        "message": "Local model switching is disabled. Please switch models in the algorithm service.",
        "algorithm": algorithm_client.get_state(),
    }


@app.get("/api/whitelist")
def whitelist_items(user: dict = Depends(current_user)):
    return {"items": whitelist_store.list_items()}


@app.post("/api/whitelist")
def create_whitelist_item(req: WhitelistCreateRequest, user: dict = Depends(current_admin)):
    try:
        item = whitelist_store.upsert(req.plate_no, req.owner, req.note)
        local_model.clear_gate_memory(req.plate_no)
        auth_store.add_audit(user["username"], "upsert_whitelist", req.plate_no, req.note)
        return item
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/whitelist/{plate_no}")
def delete_whitelist_item(plate_no: str, user: dict = Depends(current_admin)):
    removed = whitelist_store.delete(plate_no)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Whitelist plate not found: {plate_no}")
    local_model.clear_gate_memory(plate_no)
    auth_store.add_audit(user["username"], "delete_whitelist", plate_no, "删除白名单车辆")
    return {"removed": True, "plate_no": plate_no}


@app.post("/api/whitelist/decision", response_model=GateDecision)
def gate_decision(req: GateDecisionRequest) -> GateDecision:
    identity = req.plate_no or req.electronic_id
    decision = decide_plate(identity, req.confidence)
    return GateDecision(
        plate_no=decision.plate_no or req.plate_no,
        electronic_id=req.electronic_id,
        whitelist_status=decision.whitelist_status,
        gate_action=decision.gate_action,
        confidence=req.confidence,
        reason=decision.reason,
        created_at=_now(),
    )
