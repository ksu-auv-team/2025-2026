# Camera Package

The camera package handles frame acquisition from USB webcams and the ZED 2i stereo camera, runs YOLOv8 object detection on each frame, and exposes an MJPEG streaming server so any browser on the network can watch live annotated feeds.

---

## Architecture

```
camera_manager.run()
  ├── ZedCamera (thread)            # pyzed → RGBA frames → BGR → YOLO → depth lookup → post
  ├── UsbCamera (thread)            # OpenCV → BGR frames → YOLO → post
  └── FastAPI streaming server      # MJPEG /stream/zed  /stream/usb
          │
          ▼
    frame_buffer: dict[str, bytes]  # shared between threads and the HTTP server
    lock: threading.Lock            # guards every read/write of frame_buffer
```

| File | Role |
|---|---|
| `camera_manager.py` | Entry point — reads env vars, starts camera threads, runs uvicorn |
| `cameras/usb_camera.py` | `UsbCamera` — OpenCV capture, YOLO inference, ZED-avoidance logic |
| `cameras/zed_camera.py` | `ZedCamera` — pyzed capture, depth measurement, YOLO inference |
| `detection/detector.py` | `ObjectDetector` wrapper around `ultralytics.YOLO`; `Detection` dataclass |
| `streaming/server.py` | FastAPI app with MJPEG `/stream/zed`, `/stream/usb`, and a dashboard `/` |

---

## Camera backends

### USB camera (`UsbCamera`)

Uses OpenCV `VideoCapture`. On Linux it reads `/sys/class/video4linux/videoN/name` to skip device nodes whose name contains `"zed"`, preventing the USB camera thread from accidentally grabbing the ZED 2i's virtual video device. The starting device index is controlled by `USB_CAMERA_INDEX`.

### ZED 2i (`ZedCamera`)

Uses the ZED SDK (`pyzed`). Opens at 720p, `PERFORMANCE` depth mode, metric units, 20 m max depth. For every detected object the centre pixel is queried for depth so a distance (metres) is stored alongside the bounding box.

If `pyzed` is not installed, the ZED thread logs an error and exits immediately — the rest of the package continues normally.

---

## Object detection (`ObjectDetector`)

Wraps `ultralytics.YOLO`. Bounding boxes are normalised to `[0, 1]` relative to the frame dimensions so they are resolution-independent in the database.

If `ultralytics` is not installed, `detect()` returns an empty list and a warning is logged.

### `Detection` dataclass

| Field | Type | Description |
|---|---|---|
| `class_name` | `str` | YOLO class label |
| `confidence` | `float` | Detection confidence (0–1) |
| `bbox_x` | `float` | Normalised top-left x |
| `bbox_y` | `float` | Normalised top-left y |
| `bbox_w` | `float` | Normalised width |
| `bbox_h` | `float` | Normalised height |

---

## Streaming server

A minimal FastAPI app served by uvicorn on `CAMERA_STREAM_HOST:CAMERA_STREAM_PORT`.

| Route | Description |
|---|---|
| `GET /` | HTML dashboard showing both feeds side-by-side |
| `GET /stream/zed` | MJPEG stream from the ZED 2i |
| `GET /stream/usb` | MJPEG stream from the USB webcam |

Streams run at ~30 fps (`asyncio.sleep(0.033)`). If a camera has not produced a frame yet, a grey `NO SIGNAL` placeholder JPEG is sent instead.

---

## Database integration

Each detection is posted to the DB Manager's `detections` table via `AUVClient`. The `CAMERA` field is `"zed"` or `"usb"`. `DISTANCE` is `-1.0` for USB detections (no depth sensor).

---

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `ZED_CAMERA` | `false` | Set `true` to enable the ZED 2i thread |
| `USB_CAMERA` | `false` | Set `true` to enable the USB webcam thread |
| `USB_CAMERA_INDEX` | `0` | `/dev/videoN` index to start scanning from |
| `CAMERA_STREAM_HOST` | `0.0.0.0` | Bind address for the MJPEG server |
| `CAMERA_STREAM_PORT` | `8001` | Port for the MJPEG server |
| `YOLO_MODEL` | `yolov8n.pt` | Path to a YOLOv8 `.pt` weights file |
| `YOLO_CONF` | `0.5` | Minimum confidence threshold for detections |

---

## Running standalone

```bash
# enable at least one camera in .env first, e.g.:
# ZED_CAMERA=false
# USB_CAMERA=true
# USB_CAMERA_INDEX=0

uv run python -c "from libs.camera_package.camera_manager import run; run()"
```

Or via `ProcessManager` / the TUI (service name `"camera"`):

```python
from libs.process_manager import ProcessManager
pm = ProcessManager()
pm.start("camera")
```

Live feeds at `http://localhost:8001` once the service is running.

---

## Dependencies

| Package | Purpose |
|---|---|
| `opencv-python` | USB camera capture and JPEG encoding |
| `ultralytics` | YOLOv8 inference |
| `pyzed` | ZED SDK Python bindings (optional; local wheel for aarch64) |
| `numpy` | Frame manipulation and depth value handling |
| `uvicorn` / `fastapi` | MJPEG streaming server |
