import argparse
import time
from pathlib import Path

import cv2


def main() -> int:
    parser = argparse.ArgumentParser(description="Test ESP32-CAM MJPEG stream.")
    parser.add_argument("--url", required=True, help="ESP32-CAM stream URL, for example http://192.168.1.88:81/stream")
    parser.add_argument("--seconds", type=float, default=10.0, help="Test duration in seconds.")
    parser.add_argument("--out", default="esp32_cam_snapshot.jpg", help="Output snapshot path.")
    parser.add_argument("--show", action="store_true", help="Show live preview window.")
    args = parser.parse_args()

    cap = cv2.VideoCapture(args.url)
    if not cap.isOpened():
        print(f"ERROR: cannot open stream: {args.url}")
        return 1

    start = time.time()
    frames = 0
    first_frame = None
    last_frame = None

    while time.time() - start < args.seconds:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("WARN: frame read failed")
            time.sleep(0.1)
            continue

        frames += 1
        if first_frame is None:
            first_frame = frame.copy()
        last_frame = frame

        if args.show:
            cv2.imshow("ESP32-CAM stream test", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    cap.release()
    if args.show:
        cv2.destroyAllWindows()

    elapsed = max(time.time() - start, 0.001)
    if last_frame is None:
        print("ERROR: stream opened but no frames were received")
        return 2

    out_path = Path(args.out)
    cv2.imwrite(str(out_path), last_frame)
    height, width = last_frame.shape[:2]
    print(f"OK: received {frames} frames in {elapsed:.2f}s")
    print(f"Resolution: {width}x{height}")
    print(f"Approx FPS: {frames / elapsed:.2f}")
    print(f"Snapshot: {out_path.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
