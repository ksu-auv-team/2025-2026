from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from libs.camera_package.detection.detector import Detection, ObjectDetector
from libs.quick_request import AUVClient

log = logging.getLogger(__name__)


def _draw(frame: np.ndarray, det: Detection, w: int, h: int) -> np.ndarray:
    x1 = int(det.bbox_x * w)
    y1 = int(det.bbox_y * h)
    x2 = int((det.bbox_x + det.bbox_w) * w)
    y2 = int((det.bbox_y + det.bbox_h) * h)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 255), 2)
    label = f"{det.class_name} {det.confidence:.2f}"
    cv2.putText(
        frame, label, (x1, max(y1 - 5, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1
    )
    return frame


class UsbCamera:
    def __init__(
        self,
        frame_buffer: dict[str, bytes],
        lock: threading.Lock,
        stop_event: threading.Event,
        detector: ObjectDetector,
        device_index: int = 0,
    ) -> None:
        self._buf = frame_buffer
        self._lock = lock
        self._stop = stop_event
        self._detector = detector
        self._device = device_index
        self._client = AUVClient()

    def run(self) -> None:
        cap = cv2.VideoCapture(self._device)
        if not cap.isOpened():
            log.error("Failed to open USB camera (device index %d)", self._device)
            return

        try:
            while not self._stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    log.warning("USB camera read failed; retrying")
                    time.sleep(0.1)
                    continue

                h, w = frame.shape[:2]
                for det in self._detector.detect(frame):
                    self._post(det)
                    frame = _draw(frame, det, w, h)

                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self._lock:
                    self._buf["usb"] = jpeg.tobytes()

                time.sleep(0.033)
        finally:
            cap.release()
            self._client.close()

    def _post(self, det: Detection) -> None:
        try:
            self._client.post(
                "detections",
                CAMERA="usb",
                CLASS_NAME=det.class_name,
                CONFIDENCE=det.confidence,
                BBOX_X=det.bbox_x,
                BBOX_Y=det.bbox_y,
                BBOX_W=det.bbox_w,
                BBOX_H=det.bbox_h,
                DISTANCE=-1.0,
            )
        except Exception:
            log.debug("Failed to post USB detection", exc_info=True)
