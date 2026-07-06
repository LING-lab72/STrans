from pydantic import BaseModel, Field


class VideoStartRequest(BaseModel):
    source: str = Field(..., min_length=1, description="Camera index, local file path, RTSP URL, or HTTP MJPEG URL.")


class VideoStatus(BaseModel):
    running: bool
    source: str | None = None
    connected: bool = False
    frame_width: int | None = None
    frame_height: int | None = None
    frames_received: int = 0
    fps: float = 0.0
    last_error: str | None = None
