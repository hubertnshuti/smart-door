"""
Camera capture using Picamera2 (the Bookworm / libcamera stack).

Runs a background thread that always holds the latest frame, so both the
recognition loop and the web live-stream can read it without blocking.
Frames are stored in BGR (OpenCV / InsightFace convention).
"""
import threading
import time

import cv2
import numpy as np
from picamera2 import Picamera2

import config


class Camera:
    def __init__(self):
        self.picam = Picamera2()
        cfg = self.picam.create_preview_configuration(
            main={"size": (config.CAMERA_WIDTH, config.CAMERA_HEIGHT),
                  "format": "RGB888"}
        )
        self.picam.configure(cfg)
        self.picam.start()
        time.sleep(1)  # let the sensor warm up

        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        while self._running:
            rgb = self.picam.capture_array()          # RGB
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR) # -> BGR for OpenCV
            with self._lock:
                self._frame = bgr
            time.sleep(0.03)  # ~30 fps cap

    def get_frame(self):
        """Return the most recent BGR frame (numpy array) or None."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self):
        """Return the latest frame encoded as JPEG bytes (for streaming)."""
        frame = self.get_frame()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame)
        return buf.tobytes() if ok else None

    def stop(self):
        self._running = False
        time.sleep(0.1)
        try:
            self.picam.stop()
        except Exception:
            pass
