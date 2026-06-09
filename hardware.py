"""
Hardware control: MG995 servo (door latch) and buzzer (alarm).

Uses gpiozero with the lgpio pin factory (no daemon needed).
The servo moves in small steps for slow, smooth motion, then detaches
after each move to stop software-PWM jitter and save power.
"""
import threading
import time

from gpiozero import AngularServo, Buzzer
from gpiozero.pins.lgpio import LGPIOFactory

import config

_factory = LGPIOFactory()


class DoorHardware:
    def __init__(self):
        # MG995: ~0.5ms-2.5ms pulse range maps to 0-180 degrees.
        self.servo = AngularServo(
            config.SERVO_PIN,
            min_angle=0,
            max_angle=180,
            min_pulse_width=0.0005,
            max_pulse_width=0.0025,
            pin_factory=_factory,
        )
        self.buzzer = Buzzer(config.BUZZER_PIN, pin_factory=_factory)
        self._lock = threading.Lock()
        self._relock_timer = None
        self.is_open = False
        self.lock_door()  # start in a known (locked) state

    # ----- servo -----
    @staticmethod
    def _clamp(value):
        # Keep the angle safely inside 0-180 to avoid rounding errors.
        return max(0.0, min(180.0, float(value)))

    def _set_angle(self, angle):
        # Slow movement that the servo actually obeys.
        # The MG995 moves at its own fast speed between targets, so to make
        # motion look slow we send LARGER steps and wait long enough for the
        # servo to physically reach each one before sending the next.
        #
        #   STEP  = degrees per step  (bigger  = each move is more visible)
        #   DELAY = pause per step    (must be long enough to arrive)
        STEP = 5.0
        DELAY = 0.15

        angle = self._clamp(angle)
        current = self.servo.angle
        if current is None:
            # Position unknown (startup): snap directly to target once.
            self.servo.angle = angle
            time.sleep(0.5)
            self.servo.detach()
            return

        current = float(current)
        if angle > current:
            a = current
            while a < angle:
                a = min(a + STEP, angle)
                self.servo.angle = self._clamp(a)
                time.sleep(DELAY)
        else:
            a = current
            while a > angle:
                a = max(a - STEP, angle)
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
        self._relock_timer = threading.Timer(
            config.RELOCK_DELAY_SECONDS, self.lock_door
        )
        self._relock_timer.daemon = True
        self._relock_timer.start()

    # ----- buzzer -----
    def alarm(self, seconds=3):
        """Beep for a few seconds in a background thread (non-blocking)."""
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