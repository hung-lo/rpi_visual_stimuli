from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


SUPPORTED_PHOTODIODE_CORNERS = (
    "top_left",
    "top_right",
    "bottom_left",
    "bottom_right",
)


class ConfigurationError(ValueError):
    """Raised when configuration validation fails."""


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{name} must be an object")
    return value


def _require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{name} must be a boolean")
    return value


def _require_int(value: Any, name: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise ConfigurationError(f"{name} must be >= {minimum}")
    return value


def _require_float(value: Any, name: str, *, greater_than: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be numeric")
    numeric = float(value)
    if greater_than is not None and numeric <= greater_than:
        raise ConfigurationError(f"{name} must be > {greater_than}")
    return numeric


def _require_path_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _require_rgb(value: Any, name: str) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ConfigurationError(f"{name} must be a list of three RGB values")
    rgb = tuple(_require_int(channel, f"{name}[{index}]", minimum=0) for index, channel in enumerate(value))
    if any(channel > 255 for channel in rgb):
        raise ConfigurationError(f"{name} values must be in 0..255")
    return rgb


def _patch_bounds(width_px: int, height_px: int, corner: str, size_px: int, margin_px: int) -> tuple[int, int, int, int]:
    if corner == "top_left":
        left = margin_px
        top = margin_px
    elif corner == "top_right":
        left = width_px - size_px - margin_px
        top = margin_px
    elif corner == "bottom_left":
        left = margin_px
        top = height_px - size_px - margin_px
    else:
        left = width_px - size_px - margin_px
        top = height_px - size_px - margin_px
    return left, top, left + size_px, top + size_px


@dataclass(frozen=True)
class ScreenConfig:
    width_px: int
    height_px: int
    refresh_rate_hz: int
    colormode: int
    background_gray_u8: int
    visible_width_cm: float
    visible_height_cm: float

    @property
    def pixels_per_cm_x(self) -> float:
        return self.width_px / self.visible_width_cm

    @property
    def pixels_per_cm_y(self) -> float:
        return self.height_px / self.visible_height_cm

    def to_dict(self) -> dict[str, Any]:
        return {
            "width_px": self.width_px,
            "height_px": self.height_px,
            "refresh_rate_hz": self.refresh_rate_hz,
            "colormode": self.colormode,
            "background_gray_u8": self.background_gray_u8,
            "visible_width_cm": self.visible_width_cm,
            "visible_height_cm": self.visible_height_cm,
        }


@dataclass(frozen=True)
class PhotodiodeConfig:
    enabled: bool
    corner: str
    size_px: int
    margin_px: int
    on_rgb: tuple[int, int, int]
    off_rgb: tuple[int, int, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "corner": self.corner,
            "size_px": self.size_px,
            "margin_px": self.margin_px,
            "on_rgb": list(self.on_rgb),
            "off_rgb": list(self.off_rgb),
        }


@dataclass(frozen=True)
class GPIOConfig:
    enabled: bool
    ttl_pin_bcm: int
    pulse_sec: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "ttl_pin_bcm": self.ttl_pin_bcm,
            "pulse_sec": self.pulse_sec,
        }


@dataclass(frozen=True)
class CameraConfig:
    host: str
    remote_repo: str
    remote_start: str
    remote_stop: str
    remote_video_root: str
    framerate: int
    default_prestim_baseline_minutes: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "remote_repo": self.remote_repo,
            "remote_start": self.remote_start,
            "remote_stop": self.remote_stop,
            "remote_video_root": self.remote_video_root,
            "framerate": self.framerate,
            "default_prestim_baseline_minutes": self.default_prestim_baseline_minutes,
        }


@dataclass(frozen=True)
class SystemConfig:
    output_root: Path
    cache_root: Path
    screen: ScreenConfig
    photodiode: PhotodiodeConfig
    gpio: GPIOConfig
    camera: CameraConfig

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_root": str(self.output_root),
            "cache_root": str(self.cache_root),
            "screen": self.screen.to_dict(),
            "photodiode": self.photodiode.to_dict(),
            "gpio": self.gpio.to_dict(),
            "camera": self.camera.to_dict(),
        }


def _validate_screen(screen: ScreenConfig) -> None:
    if screen.width_px <= 0 or screen.height_px <= 0:
        raise ConfigurationError("screen dimensions must be positive")
    if screen.refresh_rate_hz <= 0:
        raise ConfigurationError("screen.refresh_rate_hz must be positive")
    if screen.colormode <= 0:
        raise ConfigurationError("screen.colormode must be positive")
    if not 0 <= screen.background_gray_u8 <= 255:
        raise ConfigurationError("screen.background_gray_u8 must be in 0..255")
    if screen.visible_width_cm <= 0 or screen.visible_height_cm <= 0:
        raise ConfigurationError("screen visible physical dimensions must be positive")


def _validate_photodiode(screen: ScreenConfig, photodiode: PhotodiodeConfig) -> None:
    if photodiode.corner not in SUPPORTED_PHOTODIODE_CORNERS:
        raise ConfigurationError(
            f"photodiode.corner must be one of {SUPPORTED_PHOTODIODE_CORNERS}"
        )
    if photodiode.size_px <= 0:
        raise ConfigurationError("photodiode.size_px must be positive")
    if photodiode.margin_px < 0:
        raise ConfigurationError("photodiode.margin_px must be >= 0")
    left, top, right, bottom = _patch_bounds(
        screen.width_px,
        screen.height_px,
        photodiode.corner,
        photodiode.size_px,
        photodiode.margin_px,
    )
    if left < 0 or top < 0 or right > screen.width_px or bottom > screen.height_px:
        raise ConfigurationError("photodiode patch lies outside the framebuffer")


def _validate_camera(camera: CameraConfig) -> None:
    if not camera.host.strip():
        raise ConfigurationError("camera.host must be non-empty")
    for field_name in ("remote_repo", "remote_start", "remote_stop", "remote_video_root"):
        value = getattr(camera, field_name)
        if not value.strip():
            raise ConfigurationError(f"camera.{field_name} must be non-empty")
        if not value.startswith("/"):
            raise ConfigurationError(f"camera.{field_name} must be an absolute path")
    if camera.framerate <= 0:
        raise ConfigurationError("camera.framerate must be positive")
    if camera.default_prestim_baseline_minutes <= 0:
        raise ConfigurationError("camera.default_prestim_baseline_minutes must be positive")


def _validate_gpio(gpio: GPIOConfig) -> None:
    if gpio.ttl_pin_bcm < 0:
        raise ConfigurationError("gpio.ttl_pin_bcm must be >= 0")
    if gpio.pulse_sec <= 0:
        raise ConfigurationError("gpio.pulse_sec must be positive")


def load_system_config(path: str | Path) -> SystemConfig:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigurationError("top-level configuration must be an object")

    screen_payload = _require_mapping(payload.get("screen"), "screen")
    screen = ScreenConfig(
        width_px=_require_int(screen_payload.get("width_px"), "screen.width_px", minimum=1),
        height_px=_require_int(screen_payload.get("height_px"), "screen.height_px", minimum=1),
        refresh_rate_hz=_require_int(screen_payload.get("refresh_rate_hz"), "screen.refresh_rate_hz", minimum=1),
        colormode=_require_int(screen_payload.get("colormode"), "screen.colormode", minimum=1),
        background_gray_u8=_require_int(screen_payload.get("background_gray_u8"), "screen.background_gray_u8", minimum=0),
        visible_width_cm=_require_float(screen_payload.get("visible_width_cm"), "screen.visible_width_cm", greater_than=0.0),
        visible_height_cm=_require_float(screen_payload.get("visible_height_cm"), "screen.visible_height_cm", greater_than=0.0),
    )
    _validate_screen(screen)
    if screen.background_gray_u8 > 255:
        raise ConfigurationError("screen.background_gray_u8 must be in 0..255")

    photodiode_payload = _require_mapping(payload.get("photodiode"), "photodiode")
    photodiode = PhotodiodeConfig(
        enabled=_require_bool(photodiode_payload.get("enabled"), "photodiode.enabled"),
        corner=_require_path_string(photodiode_payload.get("corner"), "photodiode.corner"),
        size_px=_require_int(photodiode_payload.get("size_px"), "photodiode.size_px", minimum=1),
        margin_px=_require_int(photodiode_payload.get("margin_px"), "photodiode.margin_px", minimum=0),
        on_rgb=_require_rgb(photodiode_payload.get("on_rgb"), "photodiode.on_rgb"),
        off_rgb=_require_rgb(photodiode_payload.get("off_rgb"), "photodiode.off_rgb"),
    )
    _validate_photodiode(screen, photodiode)

    gpio_payload = _require_mapping(payload.get("gpio"), "gpio")
    gpio = GPIOConfig(
        enabled=_require_bool(gpio_payload.get("enabled"), "gpio.enabled"),
        ttl_pin_bcm=_require_int(gpio_payload.get("ttl_pin_bcm"), "gpio.ttl_pin_bcm", minimum=0),
        pulse_sec=_require_float(gpio_payload.get("pulse_sec"), "gpio.pulse_sec", greater_than=0.0),
    )
    _validate_gpio(gpio)

    camera_payload = _require_mapping(payload.get("camera"), "camera")
    camera = CameraConfig(
        host=_require_path_string(camera_payload.get("host"), "camera.host"),
        remote_repo=_require_path_string(camera_payload.get("remote_repo"), "camera.remote_repo"),
        remote_start=_require_path_string(camera_payload.get("remote_start"), "camera.remote_start"),
        remote_stop=_require_path_string(camera_payload.get("remote_stop"), "camera.remote_stop"),
        remote_video_root=_require_path_string(camera_payload.get("remote_video_root"), "camera.remote_video_root"),
        framerate=_require_int(camera_payload.get("framerate"), "camera.framerate", minimum=1),
        default_prestim_baseline_minutes=_require_float(
            camera_payload.get("default_prestim_baseline_minutes"),
            "camera.default_prestim_baseline_minutes",
            greater_than=0.0,
        ),
    )
    _validate_camera(camera)

    system = SystemConfig(
        output_root=Path(_require_path_string(payload.get("output_root"), "output_root")),
        cache_root=Path(_require_path_string(payload.get("cache_root"), "cache_root")),
        screen=screen,
        photodiode=photodiode,
        gpio=gpio,
        camera=camera,
    )
    return system


def default_system_config_path(repo_root: str | Path | None = None) -> Path:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]
    return Path(repo_root) / "config" / "system_config.json"
