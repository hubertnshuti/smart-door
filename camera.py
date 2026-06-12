"""
Camera abstraction.

RealCamera   — Picamera2 (Raspberry Pi / libcamera stack)
MockCamera   — OpenCV VideoCapture(0) laptop webcam; produces real frames
               so face recognition genuinely works in testing.

get_camera() — factory; picks Real when Picamera2 is importable, Mock otherwise.
               Override: FORCE_MOCK_CAMERA=1
"""
import os
import threading
import time

import cv2
import config


class CameraBase:
    def get_frame(self): raise NotImplementedError   # -> np.ndarray | None
    def get_jpeg(self):  raise NotImplementedError   # -> bytes | None
    def stop(self): pass


class RealCamera(CameraBase):
    def __init__(self):
        from picamera2 import Picamera2
        self.picam = Picamera2()
        cfg = self.picam.create_preview_configuration(
            main={"size": (config.CAMERA_WIDTH, config.CAMERA_HEIGHT),
                  "format": "RGB888"}
        )
        self.picam.configure(cfg)
        self.picam.start()
        time.sleep(1)
        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self):
        while self._running:
            rgb = self.picam.capture_array()
            bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
            with self._lock:
                self._frame = bgr
            time.sleep(0.03)

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self):
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


class MockCamera(CameraBase):
    def __init__(self):
        self._cap = cv2.VideoCapture(0)
        if not self._cap.isOpened():
            print("[MOCK camera] WARNING: no webcam found — frames will be blank")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH,  config.CAMERA_WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
        self._frame = None
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        time.sleep(0.3)

    def _capture_loop(self):
        while self._running:
            ok, frame = self._cap.read()
            if ok:
                with self._lock:
                    self._frame = frame
            time.sleep(0.03)

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_jpeg(self):
        frame = self.get_frame()
        if frame is None:
            return None
        ok, buf = cv2.imencode(".jpg", frame)
        return buf.tobytes() if ok else None

    def stop(self):
        self._running = False
        time.sleep(0.1)
        self._cap.release()


def get_camera() -> CameraBase:
    if os.environ.get("FORCE_MOCK_CAMERA", "").strip("\"'") == "1":
        print("[camera] FORCE_MOCK_CAMERA -> MockCamera")
        return MockCamera()
    try:
        import picamera2  # noqa: F401
        cam = RealCamera()
        print("[camera] RealCamera (Picamera2)")
        return cam
    except Exception:
        print("[camera] -> MockCamera (OpenCV webcam)")
        return MockCamera()


# Legacy alias
Camera = get_camera
