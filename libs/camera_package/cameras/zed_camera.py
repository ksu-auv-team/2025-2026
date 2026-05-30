from __future__ import annotations

import logging
import threading
import time

import cv2
import numpy as np

from libs.camera_package.detection.detector import Detection, ObjectDetector
from libs.quick_request import AUVClient

log = logging.getLogger(__name__)

try:
    import pyzed.sl as sl
    _ZED_AVAILABLE = True
except ImportError:
    _ZED_AVAILABLE = False
    log.warning("pyzed SDK not installed; ZED camera unavailable")


def _draw(frame: np.ndarray, det: Detection, distance: float, w: int, h: int) -> np.ndarray:
    x1 = int(det.bbox_x * w)
    y1 = int(det.bbox_y * h)
    x2 = int((det.bbox_x + det.bbox_w) * w)
    y2 = int((det.bbox_y + det.bbox_h) * h)
    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 255), 2)
    label = f"{det.class_name} {det.confidence:.2f}"
    if distance >= 0:
        label += f" {distance:.2f}m"
    cv2.putText(
        frame, label, (x1, max(y1 - 5, 10)),
        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1,
    )
    return frame


class ZedCamera:
    def __init__(
        self,
        frame_buffer: dict[str, bytes],
        lock: threading.Lock,
        stop_event: threading.Event,
        detector: ObjectDetector,
    ) -> None:
        self._buf = frame_buffer
        self._lock = lock
        self._stop = stop_event
        self._detector = detector
        self._client = AUVClient()

    def run(self) -> None:
        if not _ZED_AVAILABLE:
            log.error("pyzed not available; ZED thread exiting")
            return

        zed = sl.Camera()
        init = sl.InitParameters()
        init.camera_resolution = sl.RESOLUTION.HD720
        init.depth_mode = sl.DEPTH_MODE.PERFORMANCE
        init.coordinate_units = sl.UNIT.METER
        init.depth_maximum_distance = 20.0

        if zed.open(init) != sl.ERROR_CODE.SUCCESS:
            log.error("Failed to open ZED 2i camera")
            return

        runtime = sl.RuntimeParameters()
        img_mat = sl.Mat()
        depth_mat = sl.Mat()

        try:
            while not self._stop.is_set():
                if zed.grab(runtime) != sl.ERROR_CODE.SUCCESS:
                    time.sleep(0.01)
                    continue

                zed.retrieve_image(img_mat, sl.VIEW.LEFT)
                zed.retrieve_measure(depth_mat, sl.MEASURE.DEPTH)

                # get_data() returns RGBA; convert to BGR for OpenCV/YOLO
                frame = cv2.cvtColor(img_mat.get_data(), cv2.COLOR_RGBA2BGR)
                h, w = frame.shape[:2]

                for det in self._detector.detect(frame):
                    cx = int((det.bbox_x + det.bbox_w / 2) * w)
                    cy = int((det.bbox_y + det.bbox_h / 2) * h)
                    # get_value returns (ERROR_CODE, np.ndarray)
                    err, val = depth_mat.get_value(cx, cy)
                    raw = float(val[0]) if hasattr(val, "__len__") else float(val)
                    distance = raw if err == sl.ERROR_CODE.SUCCESS and np.isfinite(raw) else -1.0
                    if distance >= 0:
                        log.info("Detected %s (%.0f%%) at %.2fm", det.class_name, det.confidence * 100, distance)
                    else:
                        log.info("Detected %s (%.0f%%) — distance unavailable", det.class_name, det.confidence * 100)
                    self._post(det, distance)
                    frame = _draw(frame, det, distance, w, h)

                _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
                with self._lock:
                    self._buf["zed"] = jpeg.tobytes()

                time.sleep(0.033)
        finally:
            zed.close()
            self._client.close()

    def _post(self, det: Detection, distance: float) -> None:
        try:
            self._client.post(
                "detections",
                CAMERA="zed",
                CLASS_NAME=det.class_name,
                CONFIDENCE=det.confidence,
                BBOX_X=det.bbox_x,
                BBOX_Y=det.bbox_y,
                BBOX_W=det.bbox_w,
                BBOX_H=det.bbox_h,
                DISTANCE=distance,
            )
        except Exception:
            log.debug("Failed to post ZED detection", exc_info=True)
