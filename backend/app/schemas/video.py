from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


CameraType = Literal["sandtable", "phone", "usb", "custom"]
CameraStatus = Literal["online", "offline", "connecting", "error"]
HeatmapMode = Literal["auto", "road", "frame", "off"]


class VideoStartRequest(BaseModel):
    source: str = Field(..., min_length=1, description="RTSP, HTTP MJPEG, local file path, or camera index.")
    name: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=80)


class CameraSource(BaseModel):
    camera_id: str
    name: str
    type: CameraType
    stream_url: str
    location: str
    description: str | None = None
    heatmap_mode: HeatmapMode = "auto"
    status: CameraStatus = "offline"
    selected: bool = False


class CameraCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    type: CameraType = "custom"
    stream_url: str = Field(..., min_length=1, max_length=500)
    location: str = Field(..., min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    heatmap_mode: HeatmapMode = "auto"


class CameraUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    type: CameraType | None = None
    stream_url: str | None = Field(default=None, min_length=1, max_length=500)
    location: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    heatmap_mode: HeatmapMode | None = None


class VideoStatus(BaseModel):
    running: bool
    source: str | None = None
    connected: bool = False
    frame_width: int | None = None
    frame_height: int | None = None
    frames_received: int = 0
    fps: float = 0.0
    is_static_image: bool = False
    last_error: str | None = None


class CameraStatusItem(BaseModel):
    camera_id: str
    status: VideoStatus


class RoadMaskSnapshot(BaseModel):
    camera_id: str
    status: Literal["ready", "unavailable"]
    width: int | None = None
    height: int | None = None
    mask_data_url: str | None = None
    schematic_data_url: str | None = None
    generated_at: str | None = None
    inference_ms: float | None = None
    cached: bool = False
    error: str | None = None


class StartAllRequest(BaseModel):
    camera_ids: list[str] = Field(default_factory=list, description="Empty means start all preset sandtable cameras.")
