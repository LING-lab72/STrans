from __future__ import annotations

from typing import Literal
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


EventSeverity = Literal["info", "warning", "critical"]
CongestionLevel = Literal["low", "medium", "high", "unknown"]
AlgorithmStatus = Literal["not_configured", "offline", "ready", "error"]


class DetectionConfig(BaseModel):
    confidence: float = Field(default=0.35, ge=0.05, le=0.95)
    iou: float = Field(default=0.45, ge=0.1, le=0.9)
    detection_interval_ms: int = Field(default=100, ge=50, le=5000)
    inference_size: int = Field(default=640, ge=256, le=1280)
    enabled_tasks: list[str] = Field(default_factory=lambda: ["vehicle", "tracking", "plate", "obstacle", "traffic"])


class AlgorithmServiceConfig(BaseModel):
    base_url: str = Field(default="", description="Teammate algorithm service base URL, for example http://192.168.1.20:9000")
    enabled: bool = False
    infer_path: str = "/infer"
    health_path: str = "/health"
    timeout_seconds: float = Field(default=8.0, ge=1.0, le=60.0)


class AlgorithmServiceState(BaseModel):
    config: AlgorithmServiceConfig
    status: AlgorithmStatus
    message: str = "Algorithm service is not configured."
    last_checked_at: str | None = None


class DetectionBox(BaseModel):
    bbox: list[float] = Field(..., min_length=4, max_length=4, description="[x1, y1, x2, y2] in source image pixels")
    class_name: str
    confidence: float = Field(ge=0, le=1)
    track_id: int | str | None = None
    plate: str | None = None
    whitelist_status: bool | None = None
    gate_action: Literal["allow", "deny"] | None = None
    gate_reason: str | None = None
    speed_kmh: float | None = None
    speed_cm_s: float | None = None
    predicted: bool = False
    camera_id: str | None = None


class TrafficStats(BaseModel):
    vehicle_count: int = 0
    current_count: int = 0
    count_in: int = 0
    count_out: int = 0
    density: float = 0
    avg_speed: float | None = None
    avg_speed_unit: str = "cm/s"
    speed_estimated: bool = False
    congestion_level: CongestionLevel = "unknown"


class TrafficEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex[:10]}")
    type: str
    severity: EventSeverity
    description: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    camera_id: str | None = None
    bbox: list[float] | None = None


class AnalysisResult(BaseModel):
    frame_id: int = 0
    timestamp: str | None = None
    camera_id: str | None = None
    source_width: int | None = None
    source_height: int | None = None
    inference_ms: float | None = None
    model_id: str | None = None
    detections: list[DetectionBox] = Field(default_factory=list)
    traffic_stats: TrafficStats = Field(default_factory=TrafficStats)
    events: list[TrafficEvent] = Field(default_factory=list)
    raw: dict | None = None
    error: str | None = None


class AnalysisPushRequest(AnalysisResult):
    pass


class DashboardSnapshot(BaseModel):
    algorithm: AlgorithmServiceState
    current_camera_id: str | None = None
    latest_analysis: AnalysisResult
    events: list[TrafficEvent] = Field(default_factory=list)
    config: DetectionConfig


class GateDecisionRequest(BaseModel):
    plate_no: str | None = None
    electronic_id: str | None = None
    confidence: float = Field(default=0.92, ge=0, le=1)


class WhitelistCreateRequest(BaseModel):
    plate_no: str
    owner: str = "沙盘白名单车辆"
    note: str = "准入车牌"


class AuthRequest(BaseModel):
    username: str
    password: str
    captcha_id: str
    captcha_code: str


class RegisterRequest(AuthRequest):
    pass


class AuthUser(BaseModel):
    id: int | None = None
    username: str
    role: Literal["admin", "user"]
    created_at: str | None = None
    last_login_at: str | None = None
    enabled: bool = True


class AuthResponse(BaseModel):
    token: str
    user: AuthUser


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6)


class UserAdminUpdateRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    enabled: bool | None = None


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=6)


class IncidentUpdateRequest(BaseModel):
    status: Literal["pending", "confirmed", "resolved", "false_positive"]
    note: str = Field(default="", max_length=300)


class GateDecision(BaseModel):
    plate_no: str | None = None
    electronic_id: str | None = None
    whitelist_status: bool
    gate_action: Literal["allow", "deny"]
    confidence: float
    reason: str
    created_at: str


class IntelligenceReportConfigUpdate(BaseModel):
    api_base: str = Field(default="https://api.deepseek.com/v1")
    model: str = Field(default="deepseek-chat")
    # Write-only: the API never returns the original key after it is saved.
    api_key: str | None = Field(default=None)


class IntelligenceReportGenerateRequest(BaseModel):
    camera_id: str | None = None
