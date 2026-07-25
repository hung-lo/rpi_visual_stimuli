from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Optional

from .config import GPIOConfig


@dataclass
class GPIOController:
    module: Any
    pin: int
    pulse_sec: float

    def pulse(self) -> None:
        self.module.output(self.pin, self.module.HIGH)
        time.sleep(self.pulse_sec)
        self.module.output(self.pin, self.module.LOW)

    def drive_low(self) -> None:
        self.module.output(self.pin, self.module.LOW)

    def cleanup(self) -> None:
        self.drive_low()
        self.module.cleanup(self.pin)


def setup_gpio(gpio_config: GPIOConfig) -> Optional[GPIOController]:
    if not gpio_config.enabled:
        return None
    try:
        import RPi.GPIO as GPIO
    except ImportError as exc:
        raise RuntimeError("RPi.GPIO is required when GPIO is enabled") from exc
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(gpio_config.ttl_pin_bcm, GPIO.OUT, initial=GPIO.LOW)
    return GPIOController(module=GPIO, pin=gpio_config.ttl_pin_bcm, pulse_sec=gpio_config.pulse_sec)
