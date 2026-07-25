from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

from .timestamps import utc_session_stamp


def sanitize_id(text: str) -> str:
    cleaned: list[str] = []
    for char in str(text).strip():
        if char.isalnum() or char in {"-", "_"}:
            cleaned.append(char)
        else:
            cleaned.append("_")
    return "".join(cleaned)


@dataclass(frozen=True)
class SessionContext:
    protocol_name: str
    mouse_id_raw: str
    mouse_id: str
    session_notes: str
    session_stamp: str
    session_id: str
    session_root: Path
    event_log_path: Path
    planned_sequence_path: Path
    metadata_path: Path
    session_manifest_path: Path
    video_directory: Path
    preview_directory: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "protocol_name": self.protocol_name,
            "mouse_id_raw": self.mouse_id_raw,
            "mouse_id": self.mouse_id,
            "session_notes": self.session_notes,
            "session_stamp": self.session_stamp,
            "session_id": self.session_id,
            "session_root": str(self.session_root),
            "event_log_path": str(self.event_log_path),
            "planned_sequence_path": str(self.planned_sequence_path),
            "metadata_path": str(self.metadata_path),
            "session_manifest_path": str(self.session_manifest_path),
            "video_directory": str(self.video_directory),
            "preview_directory": str(self.preview_directory),
        }


def build_session_context(
    protocol_name: str,
    mouse_id_raw: str,
    session_notes: str,
    output_root: Union[str, Path],
    *,
    session_stamp: Optional[str] = None,
) -> SessionContext:
    mouse_id = sanitize_id(mouse_id_raw) or "mouse"
    session_stamp = session_stamp or utc_session_stamp()
    session_id = f"{mouse_id}_{session_stamp}_{protocol_name}"
    session_root = Path(output_root) / session_id
    return SessionContext(
        protocol_name=protocol_name,
        mouse_id_raw=mouse_id_raw,
        mouse_id=mouse_id,
        session_notes=session_notes,
        session_stamp=session_stamp,
        session_id=session_id,
        session_root=session_root,
        event_log_path=session_root / f"{session_id}_event_log.csv",
        planned_sequence_path=session_root / f"{session_id}_planned_sequence.csv",
        metadata_path=session_root / f"{session_id}_metadata.json",
        session_manifest_path=session_root / f"{session_id}_stimulus_manifest.json",
        video_directory=session_root / "video",
        preview_directory=session_root / "preview",
    )


def create_session_directories(session: SessionContext, *, include_preview: bool = True) -> None:
    session.session_root.mkdir(parents=True, exist_ok=True)
    session.video_directory.mkdir(parents=True, exist_ok=True)
    if include_preview:
        session.preview_directory.mkdir(parents=True, exist_ok=True)
