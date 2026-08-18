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
# Raspberry Pi runtime environment
python3 -m pip install -r requirements.txt

# Development machine or when running pytest
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

After a camera-backed run, `Stop camera recording and fetch files now? [Y/n]:` defaults to yes. Enter `n` only if you intentionally want to leave the camera running for manual cleanup.

## Default Protocol Durations

The setup summary now reports the exact planned duration for the selected sequence before you confirm the run. Camera-enabled values below assume the default 3 minute prestim baseline and exclude camera stop/fetch/convert work after the visual protocol ends.

### Drifting Gratings

| Default setting | Value |
| --- | --- |
| Orientations | 8 |
| Trials per orientation | 80 |
| Total trials | 640 |
| Stimulus duration per trial | 0.5 sec |
| ITI duration per trial | 0.7 to 1.2 sec |
| Initial gray | 3 sec |
| Final gray | 3 sec |

| Planned duration | Time |
| --- | --- |
| Minimum visual protocol duration | 12 min 54 sec |
| Expected visual protocol duration | 15 min 34 sec |
| Maximum visual protocol duration | 18 min 14 sec |
| Expected camera-start-to-protocol-end duration with 3 min baseline | 18 min 31 sec |

### Retinotopy

| Mode | Total sweeps | Visual protocol duration | Camera-start-to-protocol-end duration with 3 min baseline |
| --- | --- | --- | --- |
| 2 directions | 40 | 16 min 46 sec | 19 min 43 sec |
| 4 directions | 80 | 33 min 26 sec | 36 min 23 sec |

## Runtime And Progress Display

Before `Start this session`, the setup summary prints the exact planned sequence duration. Camera-enabled runs also print a nominal camera-start-to-protocol-end duration; that value excludes cleanup/transfer and can be extended if raw loading keeps the prestim gray on-screen longer than requested.

Immediately before playback starts, the runner prints:

- the planned stimulation or sweep-sequence duration
- the final gray duration
- the expected time until protocol completion
- the estimated local completion timestamp

During playback, the console uses a single-line ASCII progress bar:

```text
[##########----------] 320/640  50.0% orientation=90.0 elapsed 7:47 ETA 7:47
```

The ETA includes the final gray epoch but excludes camera stop/fetch/convert work. Updates happen only after a full stimulus+ITI epoch for drifting gratings or a full sweep+gray epoch for retinotopy, so default retinotopy progress advances once about every 25 seconds. In non-interactive output, each progress update is emitted on its own line.

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

`--preview-only` validates configuration, builds previews and trial plans, and reports the exact planned protocol duration together with memory and disk estimates without touching RPG or camera hardware.

If the configured persistent cache root is not writable on a development machine, preview artifacts are written under `.preview_cache/` in the repository instead.

`--build-cache-only` builds and validates the persistent cache without opening the screen.

`--dry-run` validates prompts, sequence planning, and intended commands without hardware side effects.

For Box hardware RPG investigation, both protocols support `--test-rpg-return`. Use `python3 run_retinotopy.py --test --no-camera --test-rpg-return` or `python3 run_drifting_gratings.py --test --no-camera --test-rpg-return` to display one cached raw and print the bounded `display_raw()` return type, representation, and recognized timing fields. The drifting-gratings diagnostic automatically uses test-mode parameters, avoids session creation, and rejects `--camera`. These are hardware diagnostics and are not part of normal CI.

The event log keeps software request/return timestamps separate from RPG-reported performance fields. An interrupted blocking `display_raw()` call may have been physically presented without a completed event row; the photodiode remains the physical display-timing ground truth.

## Box 151 Hardware Timing

Retinotopy targets an RPG source-frame interval of about `66.7 ms` (15-Hz movement rate with four display refreshes per movement frame). Drifting gratings target about `16.7 ms` at a 60-Hz movie-frame rate. On Box 151, RPG `start_time` is integer-second Unix time; nanosecond software request/return timestamps are logged separately, and the photodiode remains the physical display-timing ground truth.

Use `scripts/box151_smoke_test.sh` for repeatable post-deployment compile, import, and CLI-help checks.

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
