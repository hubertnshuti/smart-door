"""
Hardware abstraction: servo door latch + buzzer alarm.

RealDoorHardware  — gpiozero + lgpio (Raspberry Pi only)
MockDoorHardware  — prints actions, no GPIO (Windows / dev machine)

get_hardware()    — factory; returns Real on Pi Linux, Mock otherwise.
                    Override: FORCE_MOCK_HARDWARE=1
"""
import os
import threading
import time

import config


class DoorHardwareBase:
    is_open: bool = False

    def open_door(self, auto_relock: bool = True): raise NotImplementedError
    def lock_door(self): raise NotImplementedError
    def alarm(self, seconds: int = 3): raise NotImplementedError
    def cleanup(self): pass


class RealDoorHardware(DoorHardwareBase):
    def __init__(self):
        from gpiozero import AngularServo, Buzzer
        from gpiozero.pins.lgpio import LGPIOFactory
        _factory = LGPIOFactory()
        self.servo = AngularServo(
            config.SERVO_PIN,
            min_angle=0, max_angle=180,
            min_pulse_width=0.0005, max_pulse_width=0.0025,
            pin_factory=_factory,
        )
        self.buzzer = Buzzer(config.BUZZER_PIN, pin_factory=_factory)
        self._lock = threading.Lock()
        self._relock_timer = None
        self.is_open = False
        self.lock_door()

    @staticmethod
    def _clamp(v):
        return max(0.0, min(180.0, float(v)))

    def _set_angle(self, angle):
        STEP, DELAY = 0.5, 0.01      # was 5.0, 0.15 — small steps = smooth/slow
        angle = self._clamp(angle)
        current = self.servo.angle
        if current is None:
            self.servo.angle = angle
            time.sleep(0.5)
            self.servo.detach()
            return
        current = float(current)
        step = STEP if angle > current else -STEP
        a = current
        while (step > 0 and a < angle) or (step < 0 and a > angle):
            a = min(a + step, angle) if step > 0 else max(a + step, angle)
            self.servo.angle = self._clamp(a)
            time.sleep(DELAY)
        time.sleep(0.3)
        self.servo.detach()

    def open_door(self, auto_relock=True):
        with self._lock:
            self._set_angle(config.SERVO_OPEN_ANGLE)
            self.is_open = True
        if auto_relock:
            self._schedule_relock()

    def lock_door(self):
        with self._lock:
            if self._relock_timer:
                self._relock_timer.cancel()
                self._relock_timer = None
            self._set_angle(config.SERVO_LOCKED_ANGLE)
            self.is_open = False

    def _schedule_relock(self):
        if self._relock_timer:
            self._relock_timer.cancel()
        self._relock_timer = threading.Timer(config.RELOCK_DELAY_SECONDS, self.lock_door)
        self._relock_timer.daemon = True
        self._relock_timer.start()

    def alarm(self, seconds=3):
        def _beep():
            self.buzzer.beep(on_time=0.2, off_time=0.2,
                             n=int(seconds / 0.4), background=False)
        threading.Thread(target=_beep, daemon=True).start()

    def cleanup(self):
        try:
            if self._relock_timer:
                self._relock_timer.cancel()
            self.servo.close()
            self.buzzer.close()
        except Exception:
            pass


class MockDoorHardware(DoorHardwareBase):
    def __init__(self):
        self.is_open = False
        self._relock_timer = None

    def open_door(self, auto_relock=True):
        self.is_open = True
        print("[MOCK] door opened")
        if auto_relock:
            if self._relock_timer:
                self._relock_timer.cancel()
            self._relock_timer = threading.Timer(
                config.RELOCK_DELAY_SECONDS, self.lock_door
            )
            self._relock_timer.daemon = True
            self._relock_timer.start()

    def lock_door(self):
        if self._relock_timer:
            self._relock_timer.cancel()
            self._relock_timer = None
        self.is_open = False
        print("[MOCK] door locked")

    def alarm(self, seconds=3):
        print(f"[MOCK] alarm {seconds}s")

    def cleanup(self):
        if self._relock_timer:
            self._relock_timer.cancel()
        print("[MOCK] hardware cleanup")


def get_hardware() -> DoorHardwareBase:
    if os.environ.get("FORCE_MOCK_HARDWARE", "").strip("\"'") == "1":
        print("[hardware] FORCE_MOCK_HARDWARE -> MockDoorHardware")
        return MockDoorHardware()
    try:
        import platform
        if platform.system() != "Linux":
            raise ImportError("not Linux")
        import gpiozero  # noqa: F401
        hw = RealDoorHardware()
        print("[hardware] RealDoorHardware (gpiozero + lgpio)")
        return hw
    except Exception:
        print("[hardware] MockDoorHardware (no GPIO)")
        return MockDoorHardware()


# Legacy alias — old code did: from hardware import DoorHardware; door = DoorHardware()
# New app.py uses get_hardware() directly.
DoorHardware = get_hardware
