from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Iterable, Optional, Protocol, Union


class ConvertRawFn(Protocol):
    def __call__(
        self,
        source_rgb_path: str,
        converted_raw_path: str,
        source_frame_count: int,
        screen_width_px: int,
        screen_height_px: int,
        refreshes_per_source_frame: int,
        screen_colormode: int,
    ) -> object:
        ...


@dataclass(frozen=True)
class RawConversionResult:
    path: Path
    file_size_bytes: int
    sha256: Optional[str]
    source_frame_count: int
    refreshes_per_source_frame: int


def sha256_file(path: Union[str, Path]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_bytes(frame: object, expected_size: int) -> bytes:
    if isinstance(frame, bytes):
        data = frame
    elif isinstance(frame, bytearray):
        data = bytes(frame)
    elif hasattr(frame, "tobytes"):
        data = frame.tobytes()
    else:
        data = bytes(frame)
    if len(data) != expected_size:
        raise ValueError(f"frame byte size {len(data)} does not match expected {expected_size}")
    return data


def convert_rgb_frames_to_raw(
    frames: Iterable[object],
    *,
    frame_count: int,
    width_px: int,
    height_px: int,
    refreshes_per_source_frame: int,
    colormode: int,
    final_path: Union[str, Path],
    convert_raw_fn: ConvertRawFn,
    compute_sha256: bool = False,
) -> RawConversionResult:
    final_raw_path = Path(final_path)
    final_raw_path.parent.mkdir(parents=True, exist_ok=True)
    expected_frame_size = width_px * height_px * 3
    source_path = None
    temp_output_path = None
    actual_frame_count = 0
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=final_raw_path.parent,
            prefix=final_raw_path.stem + ".source.",
            suffix=".rgb",
            delete=False,
        ) as handle:
            source_path = Path(handle.name)
            for frame in frames:
                handle.write(_frame_bytes(frame, expected_frame_size))
                actual_frame_count += 1
            handle.flush()
            os.fsync(handle.fileno())
        if actual_frame_count != frame_count:
            raise ValueError(
                f"expected {frame_count} source frames but wrote {actual_frame_count}"
            )
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=final_raw_path.parent,
            prefix=final_raw_path.stem + ".converted.",
            suffix=".raw",
            delete=False,
        ) as handle:
            temp_output_path = Path(handle.name)
        convert_raw_fn(
            str(source_path),
            str(temp_output_path),
            frame_count,
            width_px,
            height_px,
            refreshes_per_source_frame,
            colormode,
        )
        if not temp_output_path.exists() or temp_output_path.stat().st_size <= 0:
            raise RuntimeError(f"rpg conversion produced no output at {temp_output_path}")
        checksum = sha256_file(temp_output_path) if compute_sha256 else None
        os.replace(temp_output_path, final_raw_path)
        return RawConversionResult(
            path=final_raw_path,
            file_size_bytes=final_raw_path.stat().st_size,
            sha256=checksum,
            source_frame_count=frame_count,
            refreshes_per_source_frame=refreshes_per_source_frame,
        )
    finally:
        if source_path and source_path.exists():
            source_path.unlink()
        if temp_output_path and temp_output_path.exists():
            temp_output_path.unlink()
