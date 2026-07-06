from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.schemas.video import VideoStartRequest, VideoStatus
from app.services.video_stream import VideoStreamService

app = FastAPI(title="STrans Video Gateway", version="0.1.0")
video_service = VideoStreamService()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def to_status() -> VideoStatus:
    snapshot = video_service.status()
    return VideoStatus(**snapshot.__dict__)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/video/start", response_model=VideoStatus)
def start_video(req: VideoStartRequest) -> VideoStatus:
    video_service.start(req.source.strip())
    return to_status()


@app.post("/api/video/stop", response_model=VideoStatus)
def stop_video() -> VideoStatus:
    video_service.stop()
    return to_status()


@app.get("/api/video/status", response_model=VideoStatus)
def video_status() -> VideoStatus:
    return to_status()


@app.get("/api/video/mjpeg")
def video_mjpeg() -> StreamingResponse:
    return StreamingResponse(
        video_service.mjpeg_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache"},
    )
