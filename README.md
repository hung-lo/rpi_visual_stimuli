# rpi_visual_stimuli

Headless Raspberry Pi visual-stimulus protocols for:

- retinotopic mapping
- orientation drifting gratings

The repository preserves the laboratory framebuffer workflow:

- direct `rpg` presentation without X11, pygame, PsychoPy, or OpenCV windows
- 1024 x 600 framebuffer at configured 60 Hz
- 16-bit RPG output
- white photodiode patch during stimuli and black patch during gray
- software request and return timestamps around `screen.display_raw()`
- photodiode as physical display-onset ground truth
- optional GPIO pulse output
- `/mnt/hd/<session_id>/` session directories
- planned-sequence CSV, event-log CSV, metadata JSON, and copied cache manifest
- optional remote face-camera recording and fetch
- safe cleanup on interruption or failure

`vstim_natural` remains a separate repository and is not imported at runtime here.

## Installation

Install Python dependencies:

```bash
python3 -m pip install -r requirements-dev.txt
```

System tools required on the Pi:

- `ffmpeg`
- `rsync`
- `ssh`

Install the SjulsonLab `rpg` package separately on the Raspberry Pi. It is intentionally not listed from PyPI in this repository because the laboratory install source may not be published there.

## Configuration

Shared hardware settings live in `config/system_config.json`.

The screen physical dimensions there are provisional calibration defaults. Measure the visible width and height of the actual monitor before using spatial-frequency values in cycles/cm for drifting gratings.

You can override the configuration path with:

```bash
python3 run_drifting_gratings.py --system-config /path/to/config.json
python3 run_retinotopy.py --system-config /path/to/config.json
```

## Running

Normal interactive entrypoints:

```bash
python3 run_drifting_gratings.py
python3 run_retinotopy.py
```

Camera selection options:

- `--camera`: enable camera recording without asking
- `--no-camera`: disable camera recording without asking
- no flag: prompt with `Record face camera? [Y/n]:`

The camera-enabled path shows gray with a black photodiode patch before the synchronous camera start command is issued. The photodiode signal is the physical timing ground truth; software request/return timestamps are logged for reference only.

## Cache And Sessions

Persistent caches are stored under `/mnt/hd/vstim_cache/`.

Session outputs are stored under `/mnt/hd/<session_id>/` and include:

- `<session_id>_planned_sequence.csv`
- `<session_id>_event_log.csv`
- `<session_id>_metadata.json`
- `<session_id>_stimulus_manifest.json`
- `video/`

Large persistent raw movies stay in the cache and are not copied into every session.

## Modes

Both protocols support:

- `--preview-only`
- `--build-cache-only`
- `--dry-run`
- `--test`

`--preview-only` validates configuration, builds previews and trial plans, and reports duration, memory, and disk estimates without touching RPG or camera hardware.

`--build-cache-only` builds and validates the persistent cache without opening the screen.

`--dry-run` validates prompts, sequence planning, and intended commands without hardware side effects.

## Manual Camera Cleanup

If a run leaves the camera recording, the manual cleanup command is:

```bash
cd ~/rpi_visual_stimuli
python3 remote_camera_control.py stop-fetch
```

## Validation Notes

Before animal use, follow the staged checklist in `docs/HARDWARE_VALIDATION.md`, especially:

- verify gray-with-black-patch retention after a one-frame raw
- verify retinotopy geometry and reverse-direction correctness
- verify drifting-grating orientation and drift sign
- verify RPG timing stability
- verify photodiode transitions
- verify synchronous camera start and baseline timing
