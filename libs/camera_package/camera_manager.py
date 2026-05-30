from __future__ import annotations

import logging
import signal
import sys
import threading

import uvicorn

from libs.camera_package.cameras.usb_camera import UsbCamera
from libs.camera_package.cameras.zed_camera import ZedCamera
from libs.camera_package.detection.detector import ObjectDetector
from libs.camera_package.streaming.server import create_app
from libs.config import get_env

log = logging.getLogger(__name__)


def run() -> None:
    from libs.logging_config import setup_logging
    setup_logging("camera")

    frame_buffer: dict[str, bytes] = {}
    lock = threading.Lock()
    stop_event = threading.Event()

    model_path = get_env("YOLO_MODEL", default="yolov8n.pt")
    conf = float(get_env("YOLO_CONF", default="0.5"))

    threads: list[threading.Thread] = []

    if get_env("ZED_CAMERA", default="false").lower() == "true":
        cam = ZedCamera(frame_buffer, lock, stop_event, ObjectDetector(model_path, conf))
        t = threading.Thread(target=cam.run, name="zed-camera", daemon=True)
        t.start()
        threads.append(t)
        log.info("ZED camera thread started")

    if get_env("USB_CAMERA", default="false").lower() == "true":
        device = int(get_env("USB_CAMERA_INDEX", default="0"))
        cam = UsbCamera(
            frame_buffer, lock, stop_event,
            ObjectDetector(model_path, conf),
            device_index=device,
        )
        t = threading.Thread(target=cam.run, name="usb-camera", daemon=True)
        t.start()
        threads.append(t)
        log.info("USB camera thread started (device index %d)", device)

    if not threads:
        log.warning("No cameras enabled. Set ZED_CAMERA=true or USB_CAMERA=true in .env")

    def _shutdown(sig: int, frame: object) -> None:
        log.info("Camera package shutting down (signal %d)", sig)
        stop_event.set()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    host = get_env("CAMERA_STREAM_HOST", default="0.0.0.0")
    port = int(get_env("CAMERA_STREAM_PORT", default="8001"))
    log.info("Camera stream server starting on %s:%d", host, port)

    app = create_app(frame_buffer, lock)
    uvicorn.run(app, host=host, port=port, reload=False, log_config=None)
