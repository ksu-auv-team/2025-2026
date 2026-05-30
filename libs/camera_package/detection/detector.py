from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

log = logging.getLogger(__name__)

try:
    from ultralytics import YOLO as _YOLO
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    log.warning("ultralytics not installed; object detection disabled")


@dataclass
class Detection:
    class_name: str
    confidence: float
    # All bbox values are normalised to [0, 1] relative to frame dimensions.
    bbox_x: float  # top-left x
    bbox_y: float  # top-left y
    bbox_w: float  # width
    bbox_h: float  # height


class ObjectDetector:
    def __init__(self, model_path: str = "yolov8n.pt", conf: float = 0.5) -> None:
        self._available = _AVAILABLE
        if self._available:
            self._model = _YOLO(model_path)
            self._conf = conf
        else:
            log.error("ObjectDetector created but ultralytics is not installed")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        if not self._available:
            return []
        h, w = frame.shape[:2]
        results = self._model(frame, conf=self._conf, verbose=False)
        detections: list[Detection] = []
        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                detections.append(Detection(
                    class_name=result.names[int(box.cls[0])],
                    confidence=float(box.conf[0]),
                    bbox_x=x1 / w,
                    bbox_y=y1 / h,
                    bbox_w=(x2 - x1) / w,
                    bbox_h=(y2 - y1) / h,
                ))
        return detections
