from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import PhotodiodeConfig, ScreenConfig


@dataclass(frozen=True)
class PatchGeometry:
    left: int
    top: int
    right: int
    bottom: int


def compute_patch_geometry(screen: ScreenConfig, photodiode: PhotodiodeConfig) -> PatchGeometry:
    size = photodiode.size_px
    margin = photodiode.margin_px
    if photodiode.corner == "top_left":
        left = margin
        top = margin
    elif photodiode.corner == "top_right":
        left = screen.width_px - size - margin
        top = margin
    elif photodiode.corner == "bottom_left":
        left = margin
        top = screen.height_px - size - margin
    else:
        left = screen.width_px - size - margin
        top = screen.height_px - size - margin
    return PatchGeometry(left=left, top=top, right=left + size, bottom=top + size)


def patch_rgb(photodiode: PhotodiodeConfig, *, on: bool) -> tuple[int, int, int]:
    return photodiode.on_rgb if on else photodiode.off_rgb


def apply_patch(frame: Any, geometry: PatchGeometry, rgb: tuple[int, int, int]) -> Any:
    frame[geometry.top:geometry.bottom, geometry.left:geometry.right] = rgb
    return frame


def apply_photodiode_patch(frame: Any, screen: ScreenConfig, photodiode: PhotodiodeConfig, *, on: bool) -> Any:
    if not photodiode.enabled:
        return frame
    geometry = compute_patch_geometry(screen, photodiode)
    return apply_patch(frame, geometry, patch_rgb(photodiode, on=on))
