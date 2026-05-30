from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse

log = logging.getLogger(__name__)

_HTML = """<!DOCTYPE html>
<html>
<head>
<title>AUV Camera Streams</title>
<style>
  body { background: #111; color: #eee; font-family: sans-serif; text-align: center; margin: 0; padding: 20px; }
  h1 { margin-bottom: 16px; }
  .feeds { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; }
  .feed { border: 2px solid #444; border-radius: 6px; overflow: hidden; }
  .feed img { display: block; max-width: 640px; width: 100%; }
  .feed p { margin: 6px 0; font-size: 0.85rem; color: #aaa; }
  a { color: #7bf; }
</style>
</head>
<body>
<h1>AUV Camera Feeds</h1>
<div class="feeds">
  <div class="feed">
    <img src="/stream/zed" alt="ZED 2i">
    <p>ZED 2i &mdash; <a href="/stream/zed">direct link</a></p>
  </div>
  <div class="feed">
    <img src="/stream/usb" alt="USB Webcam">
    <p>USB Webcam &mdash; <a href="/stream/usb">direct link</a></p>
  </div>
</div>
</body>
</html>"""

_NO_SIGNAL: bytes | None = None


def _no_signal_jpeg() -> bytes:
    global _NO_SIGNAL
    if _NO_SIGNAL is None:
        try:
            import cv2
            import numpy as np
            frame = np.zeros((360, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "NO SIGNAL", (150, 195), cv2.FONT_HERSHEY_SIMPLEX, 3.0, (80, 80, 80), 4)
            _, buf = cv2.imencode(".jpg", frame)
            _NO_SIGNAL = buf.tobytes()
        except Exception:
            _NO_SIGNAL = b""
    return _NO_SIGNAL


def create_app(frame_buffer: dict[str, bytes], lock: threading.Lock) -> FastAPI:
    app = FastAPI(title="AUV Camera Stream", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(_HTML)

    async def _mjpeg(camera: str) -> AsyncGenerator[bytes, None]:
        while True:
            with lock:
                jpeg = frame_buffer.get(camera)
            if not jpeg:
                jpeg = _no_signal_jpeg()
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
            await asyncio.sleep(0.033)

    @app.get("/stream/zed")
    async def stream_zed() -> StreamingResponse:
        return StreamingResponse(
            _mjpeg("zed"),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    @app.get("/stream/usb")
    async def stream_usb() -> StreamingResponse:
        return StreamingResponse(
            _mjpeg("usb"),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )

    return app
