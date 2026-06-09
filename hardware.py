"""
Hardware control: MG995 servo (door latch) and buzzer (alarm).

We use gpiozero with the pigpio pin factory because pigpio produces a stable,
hardware-timed PWM signal. Software PWM makes the MG995 jitter badly.

IMPORTANT: run the pigpio daemon first:  sudo systemctl enable --now pigpiod
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
    def _set_angle(self, angle):
        self.servo.angle = angle
        time.sleep(0.6)          # give the servo time to travel
        self.servo.detach()      # stop sending PWM -> stops jitter & saves power

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
