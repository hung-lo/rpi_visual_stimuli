from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Iterable

import numpy as np

from ...core.config import SystemConfig
from ...core.photodiode import apply_photodiode_patch
from .config import DriftingGratingConfig, RectangularPatchGeometry, normalize_orientation_deg


def drift_direction_deg(bar_orientation_deg: float) -> float:
    return (normalize_orientation_deg(bar_orientation_deg) - 90.0) % 360.0


def _coordinate_grids(system_config: SystemConfig) -> tuple[np.ndarray, np.ndarray]:
    screen = system_config.screen
    center_x_px = (screen.width_px - 1) / 2.0
    center_y_px = (screen.height_px - 1) / 2.0
    x_px = np.arange(screen.width_px, dtype=np.float64)
    y_px = np.arange(screen.height_px, dtype=np.float64)
    x_cm = (x_px - center_x_px) / screen.pixels_per_cm_x
    y_cm = (center_y_px - y_px) / screen.pixels_per_cm_y
    return np.meshgrid(x_cm, y_cm)


def _rectangular_mask(system_config: SystemConfig, geometry: RectangularPatchGeometry) -> np.ndarray:
    x_grid, y_grid = _coordinate_grids(system_config)
    half_width = geometry.width_cm / 2.0
    half_height = geometry.height_cm / 2.0
    return (
        (x_grid >= geometry.center_x_cm - half_width)
        & (x_grid <= geometry.center_x_cm + half_width)
        & (y_grid >= geometry.center_y_cm - half_height)
        & (y_grid <= geometry.center_y_cm + half_height)
    )


def generate_grating_frame(
    system_config: SystemConfig,
    config: DriftingGratingConfig,
    *,
    bar_orientation_deg: float,
    frame_index: int,
) -> np.ndarray:
    x_grid_cm, y_grid_cm = _coordinate_grids(system_config)
    theta_rad = np.deg2rad(normalize_orientation_deg(bar_orientation_deg))
    normal_x = -np.sin(theta_rad)
    normal_y = np.cos(theta_rad)
    carrier_cm = normal_x * x_grid_cm + normal_y * y_grid_cm
    phase_rad = (
        np.deg2rad(config.starting_phase_deg)
        + 2.0
        * np.pi
        * config.temporal_frequency_hz
        * frame_index
        / system_config.screen.refresh_rate_hz
    )
    sinusoid = np.sin(
        2.0 * np.pi * config.spatial_frequency_cycles_per_cm * carrier_cm + phase_rad
    )
    luminance = config.mean_luminance * (1.0 + config.contrast * sinusoid)
    frame_u8 = np.rint(luminance * 255.0).astype(np.uint8)
    if config.grating_mode == "rectangular_patch" and config.rectangular_patch_geometry is not None:
        mask = _rectangular_mask(system_config, config.rectangular_patch_geometry)
        frame_u8 = np.where(mask, frame_u8, system_config.screen.background_gray_u8)
    frame_rgb = np.repeat(frame_u8[:, :, None], 3, axis=2)
    return apply_photodiode_patch(
        frame_rgb,
        system_config.screen,
        system_config.photodiode,
        on=True,
    )


def iter_stimulus_frames(
    system_config: SystemConfig,
    config: DriftingGratingConfig,
    *,
    bar_orientation_deg: float,
) -> Iterable[np.ndarray]:
    for frame_index in range(config.stimulus_frame_count):
        yield generate_grating_frame(
            system_config,
            config,
            bar_orientation_deg=bar_orientation_deg,
            frame_index=frame_index,
        )


def generate_stimulus_frames(
    system_config: SystemConfig,
    config: DriftingGratingConfig,
    *,
    bar_orientation_deg: float,
) -> list[np.ndarray]:
    return list(iter_stimulus_frames(system_config, config, bar_orientation_deg=bar_orientation_deg))


def _import_pillow():
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required to create preview PNGs") from exc
    return Image, ImageDraw


def _orientation_label(bar_orientation_deg: float) -> str:
    return f"{bar_orientation_deg:05.1f} deg"


def save_preview_png(
    preview_path: str | Path,
    system_config: SystemConfig,
    config: DriftingGratingConfig,
    *,
    bar_orientation_deg: float,
) -> Path:
    Image, ImageDraw = _import_pillow()
    frame = generate_grating_frame(
        system_config,
        config,
        bar_orientation_deg=bar_orientation_deg,
        frame_index=0,
    )
    image = Image.fromarray(frame, mode="RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 230, 44), fill=(0, 0, 0))
    draw.text((14, 14), _orientation_label(bar_orientation_deg), fill=(255, 255, 255))
    output_path = Path(preview_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)
    return output_path


def save_contact_sheet(preview_paths: list[Path], destination_path: str | Path) -> Path:
    Image, ImageDraw = _import_pillow()
    images = [Image.open(path).convert("RGB") for path in preview_paths]
    if not images:
        raise ValueError("preview_paths cannot be empty")
    columns = min(4, len(images))
    rows = int(ceil(len(images) / columns))
    tile_width, tile_height = images[0].size
    canvas = Image.new("RGB", (columns * tile_width, rows * tile_height), color=(32, 32, 32))
    for index, image in enumerate(images):
        x = (index % columns) * tile_width
        y = (index // columns) * tile_height
        canvas.paste(image, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 12), "Drifting gratings preview", fill=(255, 255, 255))
    output_path = Path(destination_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    for image in images:
        image.close()
    return output_path
