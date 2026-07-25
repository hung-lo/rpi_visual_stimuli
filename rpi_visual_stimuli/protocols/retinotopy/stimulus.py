from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Iterable

import numpy as np

from ...core.config import SystemConfig
from ...core.photodiode import apply_photodiode_patch
from .config import RetinotopyConfig


def band_width_px(system_config: SystemConfig, config: RetinotopyConfig, direction: str) -> int:
    relevant_dimension = (
        system_config.screen.width_px
        if direction in {"left_to_right", "right_to_left"}
        else system_config.screen.height_px
    )
    return max(1, int(round(relevant_dimension * config.bar_width_fraction)))


def _blank_frame(system_config: SystemConfig) -> np.ndarray:
    return np.full(
        (
            system_config.screen.height_px,
            system_config.screen.width_px,
            3,
        ),
        system_config.screen.background_gray_u8,
        dtype=np.uint8,
    )


def _clip_range(start: int, end: int, upper_bound: int) -> tuple[int, int]:
    return max(0, start), min(upper_bound, end)


def _draw_vertical_pair(frame: np.ndarray, boundary: float, band_width: int, width_px: int) -> np.ndarray:
    boundary_px = int(round(boundary))
    black_left, black_right = _clip_range(boundary_px - band_width, boundary_px, width_px)
    white_left, white_right = _clip_range(boundary_px, boundary_px + band_width, width_px)
    if black_left < black_right:
        frame[:, black_left:black_right, :] = 0
    if white_left < white_right:
        frame[:, white_left:white_right, :] = 255
    return frame


def _draw_horizontal_pair(frame: np.ndarray, boundary: float, band_width: int, height_px: int) -> np.ndarray:
    boundary_px = int(round(boundary))
    black_top, black_bottom = _clip_range(boundary_px - band_width, boundary_px, height_px)
    white_top, white_bottom = _clip_range(boundary_px, boundary_px + band_width, height_px)
    if black_top < black_bottom:
        frame[black_top:black_bottom, :, :] = 0
    if white_top < white_bottom:
        frame[white_top:white_bottom, :, :] = 255
    return frame


def _boundary_positions(system_config: SystemConfig, config: RetinotopyConfig, direction: str) -> np.ndarray:
    width = band_width_px(system_config, config, direction)
    if direction in {"left_to_right", "right_to_left"}:
        start = -width
        end = system_config.screen.width_px + width
    else:
        start = -width
        end = system_config.screen.height_px + width
    positions = np.linspace(start, end, config.source_frame_count)
    if direction in {"right_to_left", "bottom_to_top"}:
        return positions[::-1]
    return positions


def generate_frame(
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    direction: str,
    frame_index: int,
) -> np.ndarray:
    positions = _boundary_positions(system_config, config, direction)
    position = positions[frame_index]
    width = band_width_px(system_config, config, direction)
    frame = _blank_frame(system_config)
    if direction in {"left_to_right", "right_to_left"}:
        frame = _draw_vertical_pair(frame, position, width, system_config.screen.width_px)
    else:
        frame = _draw_horizontal_pair(frame, position, width, system_config.screen.height_px)
    return apply_photodiode_patch(
        frame,
        system_config.screen,
        system_config.photodiode,
        on=True,
    )


def iter_direction_frames(
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    direction: str,
) -> Iterable[np.ndarray]:
    positions = _boundary_positions(system_config, config, direction)
    width = band_width_px(system_config, config, direction)
    for position in positions:
        frame = _blank_frame(system_config)
        if direction in {"left_to_right", "right_to_left"}:
            frame = _draw_vertical_pair(frame, position, width, system_config.screen.width_px)
        else:
            frame = _draw_horizontal_pair(frame, position, width, system_config.screen.height_px)
        yield apply_photodiode_patch(
            frame,
            system_config.screen,
            system_config.photodiode,
            on=True,
        )


def generate_direction_frames(
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    direction: str,
) -> list[np.ndarray]:
    return list(iter_direction_frames(system_config, config, direction=direction))


def _import_pillow():
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Pillow is required to create preview PNGs") from exc
    return Image, ImageDraw


def save_direction_preview(
    preview_path: str | Path,
    system_config: SystemConfig,
    config: RetinotopyConfig,
    *,
    direction: str,
) -> Path:
    Image, ImageDraw = _import_pillow()
    frames = generate_direction_frames(system_config, config, direction=direction)
    indices = [0, len(frames) // 2, len(frames) - 1]
    images = [Image.fromarray(frames[index], mode="RGB") for index in indices]
    width, height = images[0].size
    canvas = Image.new("RGB", (len(images) * width, height), color=(32, 32, 32))
    for index, image in enumerate(images):
        canvas.paste(image, (index * width, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((8, 8, 260, 42), fill=(0, 0, 0))
    draw.text((14, 14), direction, fill=(255, 255, 255))
    output_path = Path(preview_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    for image in images:
        image.close()
    return output_path


def save_contact_sheet(preview_paths: list[Path], destination_path: str | Path) -> Path:
    Image, ImageDraw = _import_pillow()
    images = [Image.open(path).convert("RGB") for path in preview_paths]
    if not images:
        raise ValueError("preview_paths cannot be empty")
    columns = min(2, len(images))
    rows = int(ceil(len(images) / columns))
    tile_width, tile_height = images[0].size
    canvas = Image.new("RGB", (columns * tile_width, rows * tile_height), color=(32, 32, 32))
    for index, image in enumerate(images):
        x = (index % columns) * tile_width
        y = (index // columns) * tile_height
        canvas.paste(image, (x, y))
    draw = ImageDraw.Draw(canvas)
    draw.text((12, 12), "Retinotopy preview", fill=(255, 255, 255))
    output_path = Path(destination_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    for image in images:
        image.close()
    return output_path
