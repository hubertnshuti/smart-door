"""
Hardware control using pigpio for smooth, jitter-free servo movement.
"""
import threading
import time
import pigpio

import config


class DoorHardware:
    def __init__(self):
        # Connect to pigpio daemon
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise RuntimeError("pigpio daemon not running. Run: sudo pigpiod")
        
        # MG995 pulse widths: 500us (0°) to 2500us (180°)
        self.SERVO_MIN_PULSE = 500   # microseconds
        self.SERVO_MAX_PULSE = 2500
        
        self.buzzer_pin = config.BUZZER_PIN
        self.servo_pin = config.SERVO_PIN
        
        # Set up buzzer as output
        self.pi.set_mode(self.buzzer_pin, pigpio.OUTPUT)
        
        self._lock = threading.Lock()
        self._relock_timer = None
        self.is_open = False
        self._current_angle = None
        
        # Start servo (hardware PWM)
        self.pi.set_mode(self.servo_pin, pigpio.OUTPUT)
        self.lock_door()
    
    def _angle_to_pulse(self, angle):
        """Convert 0-180 degrees to pulse width in microseconds."""
        pulse = self.SERVO_MIN_PULSE + (angle / 180.0) * (self.SERVO_MAX_PULSE - self.SERVO_MIN_PULSE)
        return int(pulse)
    
    def _set_angle_smooth(self, angle):
        """Smooth, dance-free servo movement."""
        angle = max(0.0, min(180.0, float(angle)))
        target_pulse = self._angle_to_pulse(angle)
        
        current = self._current_angle
        if current is None:
            # First move: just set it
            self.pi.set_servo_pulsewidth(self.servo_pin, target_pulse)
            time.sleep(0.5)
            self._current_angle = angle
            return
        
        # Move in small steps with hardware PWM
        current_pulse = self._angle_to_pulse(current)
        step_pulse = 5  # 5 microsecond steps = ~0.3° per step
        
        if target_pulse > current_pulse:
            for pulse in range(current_pulse, target_pulse + 1, step_pulse):
                self.pi.set_servo_pulsewidth(self.servo_pin, pulse)
                time.sleep(0.01)  # 10ms per step
        else:
            for pulse in range(current_pulse, target_pulse - 1, -step_pulse):
                self.pi.set_servo_pulsewidth(self.servo_pin, pulse)
                time.sleep(0.01)
        
        # Final exact position
        self.pi.set_servo_pulsewidth(self.servo_pin, target_pulse)
        time.sleep(0.2)
        self._current_angle = angle
    
    def open_door(self, auto_relock=True):
        with self._lock:
            self._set_angle_smooth(config.SERVO_OPEN_ANGLE)
            self.is_open = True
        if auto_relock:
            self._schedule_relock()
    
    def lock_door(self):
        with self._lock:
            if self._relock_timer:
                self._relock_timer.cancel()
                self._relock_timer = None
            self._set_angle_smooth(config.SERVO_LOCKED_ANGLE)
            self.is_open = False
    
    def _schedule_relock(self):
        if self._relock_timer:
            self._relock_timer.cancel()
        self._relock_timer = threading.Timer(config.RELOCK_DELAY_SECONDS, self.lock_door)
        self._relock_timer.daemon = True
        self._relock_timer.start()
    
    # ----- buzzer -----
    def alarm(self, seconds=3):
        def _beep():
            end = time.time() + seconds
            while time.time() < end:
                self.pi.write(self.buzzer_pin, 1)
                time.sleep(0.2)
                self.pi.write(self.buzzer_pin, 0)
                time.sleep(0.2)
        threading.Thread(target=_beep, daemon=True).start()
    
    def cleanup(self):
        try:
            if self._relock_timer:
                self._relock_timer.cancel()
            self.pi.set_servo_pulsewidth(self.servo_pin, 0)  # stop servo
            self.pi.write(self.buzzer_pin, 0)
            self.pi.stop()
        except Exception:
            pass