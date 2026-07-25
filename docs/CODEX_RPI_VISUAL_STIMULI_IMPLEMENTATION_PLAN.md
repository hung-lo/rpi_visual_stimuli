# Codex Implementation Plan: `rpi_visual_stimuli`

## 1. Objective

Create a new GitHub repository named:

```text
hung-lo/rpi_visual_stimuli
```

The repository will contain two Raspberry Pi visual-stimulus protocols:

1. Retinotopic mapping
2. Orientation drifting gratings

The repository must reuse the validated concepts and generic runtime behavior from:

```text
https://github.com/hung-lo/vstim_natural
```

but it must **not** modify `vstim_natural` and must not import its run scripts as a runtime dependency.

The new repository must preserve the current laboratory workflow:

- direct `rpg` framebuffer presentation;
- headless operation without X11, pygame, PsychoPy, or OpenCV windows;
- 1024 x 600 framebuffer at a configured 60 Hz refresh rate;
- 16-bit RPG output;
- photodiode timing patch;
- software request/return timestamps around `screen.display_raw()`;
- the photodiode signal as the physical display-onset ground truth;
- optional GPIO pulse output;
- `/mnt/hd/<session_id>/` session directories;
- planned-sequence CSV, event-log CSV, and metadata JSON;
- optional remote face-camera recording;
- pre-stimulus gray screen and camera baseline;
- early-start override;
- post-stimulus stop/fetch prompt;
- H.264-to-MP4 conversion;
- safe cleanup after `KeyboardInterrupt` or other failures.

Only two user-facing experiment entrypoints should exist:

```text
run_retinotopy.py
run_drifting_gratings.py
```

Each entrypoint asks whether the user wants face-camera recording. Do not create separate `_cam.py` experiment scripts.

---

## 2. Final architectural decisions

### 2.1 Repository and entrypoint names

Use:

```text
rpi_visual_stimuli/
├── run_retinotopy.py
├── run_drifting_gratings.py
└── remote_camera_control.py
```

Keep the standard scientific term **drifting gratings** consistently in the package, documentation, metadata, and session names.

### 2.2 Root scripts must remain thin

The two root run scripts are for convenient operation from the Pi:

```bash
cd ~/rpi_visual_stimuli
python3 run_retinotopy.py
python3 run_drifting_gratings.py
```

They must contain only:

- argument parsing;
- loading the system configuration;
- resolving interactive versus command-line camera selection;
- calling the protocol runner;
- top-level error reporting.

Do not place the full experiment implementation in the root scripts.

Example shape:

```python
#!/usr/bin/env python3

from rpi_visual_stimuli.protocols.retinotopy.runner import main


if __name__ == "__main__":
    raise SystemExit(main())
```

### 2.3 One script per protocol, optional camera mode

Each root script supports mutually exclusive options:

```text
--camera
--no-camera
```

Behavior:

- `--camera`: enable camera recording without asking;
- `--no-camera`: disable camera recording without asking;
- no flag: ask interactively;
- both flags: argparse error.

Interactive prompt:

```text
Record face camera? [Y/n]:
```

Use `Yes` as the default because camera recording is the normal experimental path. The user can press `n` for display-only testing.

When camera recording is disabled:

- do not ask for camera-baseline duration;
- do not start the early-start input monitor;
- do not ask whether to stop/fetch the camera afterward;
- still show and log the configured initial and final gray periods.

### 2.4 Do not directly import `vstim_natural`

Do not do this:

```python
from run_stringer_vstim import ...
```

or this:

```python
from vstim_natural.run_stringer_vstim import ...
```

Instead:

1. inspect the current production implementation;
2. copy only generic behavior into the new repository;
3. refactor it into tested shared modules;
4. record source provenance;
5. leave `vstim_natural` unchanged.

At implementation time, record the exact source commit:

```bash
cd ~/vstim_natural
git rev-parse HEAD
```

Write that commit to:

```text
docs/SOURCE_PROVENANCE.md
```

Also record the current `rpg` commit or installed package version when possible.

---

## 3. Audit findings and required corrections

These items were identified while reconciling the two original plans with the current repository and RPG behavior. Codex must follow these corrected decisions.

### 3.1 Do not copy the current camera wrapper startup order verbatim

The current public `run_stringer_vstim_cam.py` appears to start the camera and prepare raw assets before opening the RPG screen and showing gray. That does not satisfy the desired corrected baseline behavior.

The new repository must use this order whenever camera recording is enabled:

```text
open RPG screen
-> show photodiode-off gray
-> synchronously start camera
-> start camera-baseline clock after start returns
-> prepare/load any allowed assets under gray
-> satisfy camera and minimum-gray gates
-> start stimuli
```

### 3.2 Camera start must be synchronous

Do not launch `remote_camera_control.py start` in a background `Popen` and immediately begin the baseline clock.

Use a synchronous subprocess call. Set `camera_started = True` and record `baseline_start_monotonic` only after the command returns successfully.

The remote controller itself may launch the remote acquisition process with `nohup`, but the local wrapper must wait for the controller command to return.

### 3.3 Baseline gray must contain the black photodiode patch

Calling only:

```python
screen.display_greyscale(127)
```

cannot draw the black photodiode patch separately.

Build a one-frame gray RPG raw with the photodiode patch off. Display it once before camera start. The last frame should remain visible while assets are prepared and loaded.

Do not create a blocking three-minute RPG raw because that would interfere with:

- early-start input;
- asset preparation;
- raw loading;
- status updates.

Hardware testing must explicitly confirm that the displayed gray-with-black-patch frame remains on screen after the short `display_raw()` call returns.

If the framebuffer does not retain the final raw frame, implement a safe alternative and document it. Do not silently fall back to plain gray without the black patch.

### 3.4 Retinotopy bar terminology

Correct the ambiguous wording from the earlier plan:

- left-to-right and right-to-left azimuth sweeps use **vertical** black/white bands moving along the x-axis;
- top-to-bottom and bottom-to-top elevation sweeps use **horizontal** black/white bands moving along the y-axis.

### 3.5 Grating contrast must have a precise definition

Define `contrast` as Michelson contrast for a sinusoidal grating.

Use:

```python
luminance = mean_luminance * (1.0 + contrast * sinusoid)
```

For defaults:

```text
mean_luminance = 0.5
contrast = 1.0
```

this produces a 0-to-1 range.

Validate that the requested mean and contrast do not require clipping:

```python
minimum = mean_luminance * (1.0 - contrast)
maximum = mean_luminance * (1.0 + contrast)
```

Require:

```text
minimum >= 0
maximum <= 1
```

Do not use `mean_luminance + 0.5 * contrast * sinusoid` while also claiming that arbitrary `mean_luminance` values preserve Michelson contrast.

### 3.6 Screen physical dimensions are calibration values

The physical dimensions copied from MATLAB comments must be treated as provisional defaults, not as universally correct values.

Store the dimensions in the shared system configuration and require the README to explain how to measure the visible screen width and height.

Drifting-grating spatial frequency in cycles/cm is only meaningful after these values are verified for the actual stimulus monitor.

### 3.7 Namespaced camera state

The copied `remote_camera_control.py` must not share an ambiguous global state file with `vstim_natural`.

Use a new namespaced state file such as:

```text
/mnt/hd/.rpi_visual_stimuli_camera_session.json
```

Do not overwrite:

```text
/mnt/hd/.last_remote_camera_session.json
```

used by the existing repository.

### 3.8 Avoid a module named `logging.py`

Do not create:

```text
rpi_visual_stimuli/core/logging.py
```

because it can be confused with Python's standard-library `logging` module.

Use:

```text
event_logging.py
```

### 3.9 Use actual RPG raw sizes for memory checks

RPG loads converted multi-frame raws into memory, and movie memory scales with:

```text
width x height x 16 bits x source frame count
```

Use actual converted raw file sizes when available. Add a configurable overhead factor because loaded memory may exceed the exact file size.

Recommended preflight calculation:

```python
required_bytes = ceil(total_raw_file_bytes * 1.15) + safety_margin_bytes
```

Do not assume that swap makes an otherwise unsafe protocol acceptable.

### 3.10 Metadata writes must be atomic

Do not repeatedly overwrite metadata directly with `Path.write_text()`.

Use:

1. write temporary JSON in the same directory;
2. flush and optionally `fsync`;
3. `os.replace()` to the final path.

This reduces the chance of losing metadata after interruption or power failure.

---

## 4. Proposed repository layout

```text
rpi_visual_stimuli/
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── .gitignore
│
├── run_retinotopy.py
├── run_drifting_gratings.py
├── remote_camera_control.py
│
├── config/
│   └── system_config.json
│
├── rpi_visual_stimuli/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── cli.py
│   │   ├── session.py
│   │   ├── timestamps.py
│   │   ├── event_logging.py
│   │   ├── metadata.py
│   │   ├── rpg_display.py
│   │   ├── raw_conversion.py
│   │   ├── raw_cache.py
│   │   ├── photodiode.py
│   │   ├── gray_screen.py
│   │   ├── camera.py
│   │   ├── baseline.py
│   │   ├── gpio.py
│   │   ├── preflight.py
│   │   └── progress.py
│   │
│   └── protocols/
│       ├── __init__.py
│       ├── retinotopy/
│       │   ├── __init__.py
│       │   ├── config.py
│       │   ├── directions.py
│       │   ├── stimulus.py
│       │   ├── sequence.py
│       │   ├── cache.py
│       │   ├── events.py
│       │   └── runner.py
│       │
│       └── drifting_gratings/
│           ├── __init__.py
│           ├── config.py
│           ├── stimulus.py
│           ├── sequence.py
│           ├── cache.py
│           ├── events.py
│           └── runner.py
│
├── tests/
│   ├── core/
│   ├── retinotopy/
│   └── drifting_gratings/
│
└── docs/
    ├── SOURCE_PROVENANCE.md
    ├── RETINOTOPY.md
    ├── DRIFTING_GRATINGS.md
    └── HARDWARE_VALIDATION.md
```

The nested package name matching the repository name is intentional. Running either root script from the repository root will make the package importable without requiring a separate editable install.

---

## 5. Shared system configuration

Create:

```text
config/system_config.json
```

This is the single source of truth for hardware-specific settings shared by both protocols.

Suggested structure:

```json
{
  "output_root": "/mnt/hd",
  "cache_root": "/mnt/hd/vstim_cache",
  "screen": {
    "width_px": 1024,
    "height_px": 600,
    "refresh_rate_hz": 60,
    "colormode": 16,
    "background_gray_u8": 127,
    "visible_width_cm": 53.1456,
    "visible_height_cm": 29.8944
  },
  "photodiode": {
    "enabled": true,
    "corner": "top_right",
    "size_px": 120,
    "margin_px": 0,
    "on_rgb": [255, 255, 255],
    "off_rgb": [0, 0, 0]
  },
  "gpio": {
    "enabled": false,
    "ttl_pin_bcm": 23,
    "pulse_sec": 0.005
  },
  "camera": {
    "host": "pi@192.168.1.152",
    "remote_repo": "/home/pi/RPi4_behavior_boxes",
    "remote_start": "/home/pi/RPi4_behavior_boxes/video_acquisition/start_acquisition.py",
    "remote_stop": "/home/pi/RPi4_behavior_boxes/video_acquisition/stop_acquisition.sh",
    "remote_video_root": "/home/pi/stim_logs",
    "framerate": 30,
    "default_prestim_baseline_minutes": 3.0
  }
}
```

The physical dimensions are provisional until measured. Print them in every drifting-grating setup summary.

Implement immutable validated dataclasses such as:

```python
SystemConfig
ScreenConfig
PhotodiodeConfig
GPIOConfig
CameraConfig
```

Validation must catch:

- missing keys;
- wrong data types;
- invalid pixel or physical dimensions;
- nonpositive refresh rate;
- invalid RGB values;
- photodiode patch outside the framebuffer;
- invalid camera paths or empty host string.

Allow a command-line override:

```text
--system-config /path/to/config.json
```

for development or a second box.

---

## 6. Shared core modules

## 6.1 `core/timestamps.py`

Adapt the current high-resolution timing functions:

```python
capture_timestamp()
unix_ns_to_iso()
unix_ns_to_seconds_string()
utc_iso_now()
utc_session_stamp()
```

Preserve integer Unix nanoseconds and exact nine-digit decimal Unix seconds.

## 6.2 `core/session.py`

Define a `SessionContext` dataclass containing:

- protocol name;
- raw and sanitized mouse ID;
- session notes;
- session stamp;
- session ID;
- session root;
- event-log path;
- planned-sequence path;
- metadata path;
- session manifest path;
- video directory;
- preview directory if applicable.

Session naming:

```text
<mouse_id>_<YYYYMMDDThhmmssZ>_retinotopy
<mouse_id>_<YYYYMMDDThhmmssZ>_drifting_gratings
```

Do not create the session folder until after the final setup summary and user confirmation, except in an explicit dry-run output directory.

## 6.3 `core/event_logging.py`

Implement:

```python
write_csv(...)
append_csv_row(...)
```

Requirements:

- fixed field order;
- header created exactly once;
- append and flush every event;
- optionally `os.fsync()` after critical events;
- protocol-specific fields supplied by the protocol event module;
- missing values written as empty fields.

Define shared event fields:

```text
utc_iso
unix_time_utc_sec
event_type
display_request_unix_ns
display_return_unix_ns
display_return_utc_iso
display_request_perf_counter_ns
display_return_perf_counter_ns
display_call_duration_sec
start_time_unix
mean_interframe_us
stddev_interframe_us
planned_duration_sec
raw_path
notes
```

Each protocol appends its own fixed columns.

## 6.4 `core/metadata.py`

Implement:

```python
atomic_write_json(path, payload)
update_session_metadata(...)
get_git_commit(repo_root)
```

Metadata must be written initially before playback and updated in `finally`.

Always include:

- repository commit;
- source-provenance commit from `vstim_natural`;
- system configuration;
- protocol configuration;
- session identifiers;
- camera state;
- cache paths and hashes;
- preflight results;
- sequence seed;
- session stage;
- completion state;
- failure stage and exception summary when applicable;
- start and end UTC timestamps.

## 6.5 `core/rpg_display.py`

Implement a small RPG adapter rather than spreading direct RPG calls through every module.

Suggested functions:

```python
import_rpg_or_raise()
open_screen(system_config)
load_raws(screen, key_to_path)
display_raw_with_timing(screen, loaded_raw)
extract_rpg_performance(perf)
```

`display_raw_with_timing()` must capture:

1. absolute timestamp immediately before `screen.display_raw()`;
2. `perf_counter_ns` immediately before;
3. blocking RPG call;
4. `perf_counter_ns` immediately after;
5. absolute timestamp immediately after.

Documentation and metadata must state:

```text
The request timestamp is the Raspberry Pi software request immediately before
screen.display_raw(). It is not measured monitor onset. The photodiode is the
physical timing ground truth.
```

## 6.6 `core/raw_conversion.py`

Implement generic helpers for:

- streaming RGB frames to a temporary source file;
- calling `rpg.convert_raw()`;
- deleting temporary source files in `finally`;
- writing output to a temporary converted filename;
- validating nonempty output;
- atomically renaming to the final path;
- optional SHA-256 calculation.

Do not accumulate complete movies in RAM.

## 6.7 `core/raw_cache.py`

Use persistent protocol-specific caches:

```text
/mnt/hd/vstim_cache/
├── retinotopy/
└── drifting_gratings/
```

Build deterministic SHA-256 cache keys from sorted JSON containing every value that affects pixels or playback timing.

Each cache directory must contain:

```text
manifest.json
preview/
converted raw files
```

Manifest requirements:

- schema version;
- protocol cache version;
- full render configuration;
- cache hash;
- creation UTC;
- expected files;
- actual file sizes;
- optional SHA-256 for each converted raw;
- number of source frames;
- refreshes per source frame;
- planned playback duration.

Cache validation must reject:

- missing manifest;
- mismatched hash;
- missing expected file;
- zero-byte file;
- size mismatch;
- checksum mismatch when checksums are enabled.

Never copy large persistent raw movies into every session folder. Copy the small manifest to the session and record absolute raw paths.

## 6.8 `core/photodiode.py`

Implement generic patch geometry and overlay functions.

The patch must be applied after stimulus drawing so that the stimulus never covers it.

Polarity:

```text
stimulus/sweep = white
ITI/gray       = black
```

## 6.9 `core/gray_screen.py`

Build/cache gray raws keyed by:

- screen dimensions;
- colormode;
- gray level;
- photodiode configuration;
- duration in monitor refreshes.

Provide at least:

```python
get_baseline_gray_raw(...)
get_timed_gray_raw(duration_frames, ...)
```

The baseline raw may be one frame displayed briefly so its final frame remains visible. Timed ITI and final-gray raws use the requested number of monitor refreshes.

## 6.10 `core/camera.py`

Wrap calls to root-level `remote_camera_control.py`:

```python
start_camera(mouse_id, session_id)
stop_camera()
fetch_camera()
stop_and_fetch_camera()
```

Use synchronous subprocess calls for all normal operations.

The protocol runner must always pass the explicit shared session ID:

```bash
python3 remote_camera_control.py start \
    --mouse-id <mouse_id> \
    --session-id <session_id>
```

## 6.11 `core/baseline.py`

Move the reusable early-start and baseline-gate behavior into this module.

Implement:

```python
start_early_start_monitor()
stop_early_start_monitor()
wait_for_prestimulus_gate(...)
```

The gate must require both:

1. requested camera baseline elapsed, unless user override is active;
2. minimum gray exposure elapsed.

Return a `BaselineResult` dataclass containing:

- requested baseline seconds;
- actual camera baseline seconds;
- minimum gray seconds;
- actual gray seconds;
- forced/override state;
- end reason;
- baseline remaining at gate entry;
- gray remaining at gate entry;
- whether it waited for minimum gray after override.

End reasons:

```text
timer_elapsed
timer_satisfied_during_preparation
user_override
```

## 6.12 `core/gpio.py`

Implement setup, pulse, drive-low, and cleanup in one place.

Do not import `RPi.GPIO` unless GPIO is enabled.

## 6.13 `core/preflight.py`

Implement:

```python
read_meminfo()
read_mem_available_bytes()
check_memory_before_loading(...)
check_disk_space_before_build(...)
```

Memory errors must report:

- total memory;
- available memory;
- actual raw sizes;
- overhead factor;
- safety margin;
- required memory;
- shortfall;
- protocol-specific suggestions.

## 6.14 `core/progress.py`

Progress output must support variable trial durations by using the sum of remaining planned durations rather than a fixed per-trial average.

Print:

- current trial/sweep and total;
- current condition;
- elapsed time;
- estimated remaining time;
- percent complete.

---

## 7. Shared experiment lifecycle

Do not build a highly abstract generic experiment framework. Keep each protocol runner explicit, but use shared helper modules.

Both runners should follow the same broad state machine.

### 7.1 Before user confirmation

1. Parse command-line options.
2. Load and validate system configuration.
3. Collect mouse ID and optional notes.
4. Resolve camera setting from flags or prompt.
5. Collect protocol-specific settings.
6. If camera is enabled, ask for baseline duration.
7. Build the complete planned sequence and resolved seed.
8. Resolve cache requirements and estimated sizes.
9. Print final setup summary.
10. Ask for final yes/no confirmation.

No session output folder should be created if the user declines.

### 7.2 Session initialization

1. Create session folder.
2. Write planned-sequence CSV.
3. Write initial metadata atomically.
4. Copy the cache manifest into the session folder.
5. Initialize event log.
6. Set current metadata stage.

### 7.3 Camera-disabled path

1. Resolve/build all required assets before opening the screen.
2. Run disk and memory preflight.
3. Open RPG screen.
4. Load required raws.
5. Display and log initial gray.
6. Enforce minimum initial-gray duration.
7. Log `session_start`.
8. Run protocol playback.
9. Display and log final gray using an RPG raw.
10. Log `session_end`.
11. Close screen and clean GPIO.

### 7.4 Camera-enabled path

1. Ensure the baseline gray raw exists.
2. Perform protocol-specific pre-camera cache work.
3. Run disk and memory preflight.
4. Create session folder and initial metadata.
5. Open RPG screen.
6. Display photodiode-off gray and log `prestim_gray_on`.
7. Record `gray_start_monotonic`.
8. Synchronously start camera with explicit session ID.
9. Record `camera_start_returned` and set `baseline_start_monotonic`.
10. Start early-start input monitor.
11. Perform allowed asset preparation/loading while gray remains visible.
12. Wait for camera-baseline and minimum-gray gate.
13. Log `prestim_baseline_end` and `session_start`.
14. Run protocol playback.
15. Display and log final gray.
16. Log `session_end` and close RPG screen.
17. Ask:

```text
Stop camera recording and fetch files now? [y/N]:
```

18. If yes, stop, wait the established settling period, fetch, and convert.
19. If no, leave camera running and print the exact manual command from this repository.

### 7.5 Error handling

Track a human-readable `current_stage`, for example:

```text
collecting_parameters
building_cache
opening_screen
displaying_prestim_gray
starting_camera
loading_raws
waiting_for_baseline
playback
final_gray
camera_cleanup
```

On any error:

- append `session_end` when the event log exists;
- set `session_completed = false`;
- record failure stage and exception summary;
- update metadata atomically;
- drive GPIO low and clean it up;
- close the RPG screen via context manager;
- leave valid persistent caches intact;
- if the camera started, retain the existing cleanup prompt;
- do not delete remotely recorded video automatically.

---

# Part A: Retinotopic mapping

## 8. Retinotopy defaults

Use initial defaults:

```python
SWEEP_DURATION_SEC = 20.0
INTER_SWEEP_GRAY_SEC = 5.0
INITIAL_GRAY_SEC = 3.0
FINAL_GRAY_SEC = 3.0

MOVEMENT_FRAME_RATE_HZ = 15
BAR_WIDTH_FRACTION = 0.10

DEFAULT_DIRECTIONS = (
    "left_to_right",
    "top_to_bottom",
)

FOUR_DIRECTION_MODE = (
    "left_to_right",
    "right_to_left",
    "top_to_bottom",
    "bottom_to_top",
)

DEFAULT_REPEATS_PER_DIRECTION = 20
```

Require:

```python
refresh_rate_hz % movement_frame_rate_hz == 0
```

Derive:

```python
refreshes_per_movement_frame = (
    refresh_rate_hz // movement_frame_rate_hz
)
```

At the defaults:

```text
300 source frames per 20-second sweep
4 monitor refreshes per source frame
```

## 9. `RetinotopyConfig`

Create a frozen validated dataclass containing:

- sweep duration;
- inter-sweep gray duration;
- initial/final gray durations;
- movement frame rate;
- bar-width fraction;
- enabled directions;
- repeats per direction;
- sequence-order mode;
- sequence seed;
- cache version.

System-level screen and photodiode settings come from `SystemConfig`, not duplicated constants.

Validation:

- positive durations;
- positive movement frame rate;
- refresh rate divisible by movement frame rate;
- integer source-frame count within tolerance;
- `0 < bar_width_fraction < 0.5`;
- recognized unique directions;
- positive repeat count.

## 10. Direction definitions

Create canonical direction records:

```text
left_to_right
right_to_left
top_to_bottom
bottom_to_top
```

Each record contains:

```text
direction
direction_code
axis
start_edge
end_edge
movement_axis
```

Suggested codes:

```text
0 = left_to_right
1 = right_to_left
2 = top_to_bottom
3 = bottom_to_top
```

Axes:

```text
left/right sweeps = azimuth
top/bottom sweeps = elevation
```

Do not log only `Azimuth` or `Elevation`; always log the exact direction.

## 11. Retinotopy frame geometry

Every frame begins as a fresh mid-gray RGB canvas.

The stimulus is an adjacent black/white band pair. Each individual band has width:

```python
round(relevant_screen_dimension * bar_width_fraction)
```

Thus the total pair spans approximately twice the configured band width.

### 11.1 Left-to-right

Use vertical bands spanning the full display height.

For moving boundary `b`:

```text
black x range = [b - band_width, b)
white x range = [b, b + band_width)
```

Move `b` from:

```text
-band_width
```

to:

```text
screen_width + band_width
```

so the pair fully starts outside and fully ends outside.

### 11.2 Right-to-left

Generate as the exact temporal reverse of the corresponding left-to-right movie, or with mathematically equivalent reversed coordinates.

Preserve the black-left/white-right ordering in screen coordinates, making the opposite movie a true temporal reverse.

### 11.3 Top-to-bottom

Use horizontal bands spanning the full display width.

For moving boundary `b`:

```text
black y range = [b - band_width, b)
white y range = [b, b + band_width)
```

Move from fully above to fully below.

### 11.4 Bottom-to-top

Generate as the exact temporal reverse of top-to-bottom.

### 11.5 General frame requirements

- clip bands at screen boundaries;
- no stale trails;
- no uninitialized pixels;
- apply photodiode patch last;
- sweep patch remains white for the entire sweep;
- all gray files use a black patch;
- first and last frames may be fully gray because the pair is completely outside.

## 12. Retinotopy raw generation and cache

Write source RGB frames one at a time.

Call:

```python
rpg.convert_raw(
    source_rgb_path,
    converted_raw_path,
    source_frame_count,
    screen_width_px,
    screen_height_px,
    refreshes_per_movement_frame,
    screen_colormode,
)
```

Cache path:

```text
/mnt/hd/vstim_cache/retinotopy/<version_hash>/
```

Expected files:

```text
manifest.json
left_to_right.raw
top_to_bottom.raw
right_to_left.raw       # only when requested
bottom_to_top.raw       # only when requested
gray_5s.raw
preview/
```

The cache hash must include:

- cache version;
- screen resolution;
- colormode;
- refresh rate;
- movement frame rate;
- sweep duration;
- band-width fraction;
- background/black/white values;
- photodiode geometry and colors;
- requested direction set.

Do not include repeat count or sequence order in the pixel cache hash.

## 13. Retinotopy memory and disk preflight

Approximate converted data at defaults:

```text
one direction:
1024 x 600 x 2 bytes x 300 frames
approximately 351.6 MiB
```

Approximate loaded sweep data:

```text
two directions  approximately 703 MiB
four directions approximately 1.37 GiB
```

Use actual converted file sizes plus:

```text
15% overhead factor
768 MiB safety margin
```

For cache generation, account for one temporary source RGB movie plus one converted raw:

```text
temporary RGB source approximately 527 MiB
converted direction   approximately 352 MiB
```

Require peak estimate plus 1 GiB disk margin.

Delete each temporary RGB file after its direction converts so only one temporary movie exists at a time.

## 14. Retinotopy sequence

Prompt for:

1. mapping mode: original two directions or four directions;
2. repeats per direction, default 20;
3. sweep duration, default 20 seconds;
4. gray interval, default 5 seconds;
5. movement frame rate, default 15 Hz;
6. fixed or shuffled direction order.

Two-direction fixed default:

```text
left_to_right
top_to_bottom
left_to_right
top_to_bottom
...
```

Four-direction fixed default should be balanced and explicitly documented.

For shuffled mode, shuffle within each repetition so every enabled direction occurs exactly once per repetition. Save the resolved seed.

Each trial contains:

```text
trial_index
repeat_number
direction
direction_code
axis
start_edge
end_edge
planned_sweep_duration_sec
planned_gray_duration_sec
raw_path
```

## 15. Retinotopy camera-specific preparation

A missing retinotopy cache is large and must be built **before** the camera starts.

Required camera-enabled order:

```text
collect settings
-> resolve/build cache
-> disk and RAM preflight
-> confirm session
-> create session
-> open screen
-> display gray with black patch
-> start camera synchronously
-> start baseline clock
-> load already-built raws during gray
-> satisfy baseline/minimum-gray gate
-> play
```

Do not record an unexpectedly long baseline while hundreds of megabytes of retinotopy raws are being generated for the first time.

## 16. Retinotopy event fields and event types

Protocol fields:

```text
trial_index
repeat_number
direction
direction_code
axis
start_edge
end_edge
movement_frame_rate_hz
refreshes_per_movement_frame
bar_width_fraction
cache_hash
```

Event types:

```text
prestim_gray_on
camera_start_requested
camera_start_returned
prestim_baseline_start
prestim_baseline_end
session_start
sweep_display
inter_sweep_gray
final_gray
session_end
```

## 17. Retinotopy outputs

```text
/mnt/hd/<session_id>/
├── <session_id>_planned_sequence.csv
├── <session_id>_event_log.csv
├── <session_id>_metadata.json
├── <session_id>_stimulus_manifest.json
└── video/
```

Do not copy the large direction raws into the session.

---

# Part B: Orientation drifting gratings

## 18. Drifting-grating defaults

Use:

```python
ORIENTATIONS_DEG = (
    0.0,
    22.5,
    45.0,
    67.5,
    90.0,
    112.5,
    135.0,
    157.5,
)

TRIALS_PER_ORIENTATION = 80
STIM_DURATION_SEC = 0.5
ITI_BASE_SEC = 0.7
ITI_JITTER_MAX_SEC = 0.5
INITIAL_GRAY_SEC = 3.0
FINAL_GRAY_SEC = 3.0

TEMPORAL_FREQUENCY_HZ = 2.0
SPATIAL_FREQUENCY_CYCLES_PER_CM = 0.2
CONTRAST = 1.0
MEAN_LUMINANCE = 0.5
STARTING_PHASE_DEG = 0.0
GRATING_MODE = "fullscreen"
```

Default total:

```text
8 orientations
80 trials per orientation
640 trials
30 source frames per 0.5-second stimulus at 60 Hz
```

The same orientation raw is replayed each trial, which resets phase to zero as required.

Do not implement mismatch-negativity or optogenetic functionality in this repository phase.

## 19. `DriftingGratingConfig`

Create a frozen validated dataclass containing:

- orientation list;
- trials per orientation;
- stimulus duration;
- base ITI and jitter maximum;
- temporal frequency;
- spatial frequency in cycles/cm;
- Michelson contrast;
- mean luminance;
- starting phase;
- grating aperture mode;
- rectangular patch geometry when applicable;
- initial/final gray;
- sequence seed;
- cache version.

System screen dimensions and photodiode configuration come from `SystemConfig`.

Validation:

- unique orientations after normalization to `[0, 180)`;
- at least one orientation;
- positive stimulus duration;
- nonnegative base ITI and jitter;
- positive temporal and spatial frequencies;
- `0 <= contrast <= 1`;
- `0 < mean_luminance < 1`;
- requested mean/contrast range inside `[0, 1]` without clipping;
- at least one source frame;
- warn when duration times refresh rate is not near an integer;
- valid aperture geometry.

## 20. Orientation and coordinate convention

Use physical coordinates centered on the screen with positive y upward:

```python
x_cm = (x_px - center_x_px) / pixels_per_cm_x
y_cm = (center_y_px - y_px) / pixels_per_cm_y
```

Define `bar_orientation_deg` as an unoriented line angle modulo 180 degrees, measured counterclockwise from the positive x-axis:

```text
0 degrees  = horizontal bars
90 degrees = vertical bars
```

For angle `theta`:

```python
theta_rad = np.deg2rad(bar_orientation_deg)
normal_x = -np.sin(theta_rad)
normal_y =  np.cos(theta_rad)
carrier_cm = normal_x * x_cm + normal_y * y_cm
```

This makes the carrier perpendicular to the visible bars.

Use increasing temporal phase:

```python
phase_rad = (
    np.deg2rad(starting_phase_deg)
    + 2.0 * np.pi * temporal_frequency_hz
      * frame_index / refresh_rate_hz
)
```

Use:

```python
sinusoid = np.sin(
    2.0 * np.pi * spatial_frequency_cycles_per_cm * carrier_cm
    + phase_rad
)
```

With this sign convention, the pattern moves opposite the normal vector as phase increases.

Log:

```python
drift_direction_deg = (bar_orientation_deg - 90.0) % 360.0
```

where drift direction is measured counterclockwise from positive x in the same physical coordinate system.

Add tests and preview animations/frames that confirm this sign convention. Do not rely on intuition alone.

## 21. Grating luminance generation

Use Michelson contrast:

```python
luminance = mean_luminance * (1.0 + contrast * sinusoid)
frame_u8 = np.rint(luminance * 255.0).astype(np.uint8)
```

Do not clip under normal validated configurations.

Convert grayscale to RGB with identical channels, then apply the photodiode patch last.

At defaults:

```text
phase increment = 360 degrees x 2 Hz / 60 Hz
                = 12 degrees per frame
```

The 30-frame movie contains one full temporal cycle.

## 22. Aperture modes

Support:

```text
fullscreen
rectangular_patch
```

For `rectangular_patch`:

- geometry is entered in physical centimeters;
- convert to pixels using calibrated screen dimensions;
- validate the complete rectangle lies inside the visible display;
- outside the aperture remains mid-gray.

Use `fullscreen` as the initial default.

Do not add circular or Gaussian apertures in Phase 1.

## 23. Drifting-grating trial sequence

Build 80 trials per orientation, then globally shuffle all trials with a local RNG:

```python
rng = random.Random(resolved_seed)
```

Do not enforce avoidance of adjacent repeated orientations; the MATLAB reference permits ordinary global randomization.

For each trial:

1. draw continuous jitter from `[0, jitter_max)`;
2. calculate requested ITI;
3. quantize to nearest monitor frame;
4. store both requested and actual frame-locked values.

```python
jitter_requested_sec = rng.random() * iti_jitter_max_sec
requested_iti_sec = iti_base_sec + jitter_requested_sec
iti_frames = max(1, round(requested_iti_sec * refresh_rate_hz))
planned_iti_sec = iti_frames / refresh_rate_hz
```

Each trial contains:

```text
trial_index
orientation_id
bar_orientation_deg
drift_direction_deg
repeat_number
starting_phase_deg
stim_frames
planned_stim_duration_sec
jitter_requested_sec
iti_frames
planned_iti_duration_sec
grating_raw_key
iti_raw_key
```

Use zero-based `trial_index` and one-based `orientation_id`.

## 24. Drifting-grating cache

Use persistent cache:

```text
/mnt/hd/vstim_cache/drifting_gratings/<version_hash>/
```

Expected structure:

```text
manifest.json
stimulus/
    orientation_01_000p0deg.raw
    orientation_02_022p5deg.raw
    ...
gray/
    gray_42frames.raw
    gray_43frames.raw
    ...
preview/
    orientation PNGs
    contact sheet
```

Stimulus-cache hash includes:

- screen pixel and physical dimensions;
- refresh rate;
- colormode;
- orientation list;
- temporal frequency;
- spatial frequency;
- stimulus frame count;
- mean luminance;
- Michelson contrast;
- starting phase;
- aperture mode and geometry;
- photodiode settings;
- cache version.

Trial count, random order, and ITI jitter sequence do not affect stimulus movie pixels.

Gray raws may be cached by monitor-frame count and shared when all other rendering settings match.

## 25. Drifting-grating memory preflight

Approximate stimulus raw memory:

```text
8 x 30 x 1024 x 600 x 2 bytes
approximately 281 MiB
```

A complete default trial plan can request approximately 31 unique ITI frame counts from 42 through 72. Each is a one-frame image held for multiple refreshes, so their memory is much smaller than a 30-frame movie.

Use actual converted raw sizes plus:

```text
15% overhead factor
512 MiB safety margin
```

Abort before playback if all required stimuli and ITIs cannot be loaded safely.

## 26. Drifting-grating camera preparation

Preferred camera-enabled order when cache files are missing:

```text
build baseline gray raw
-> open screen and display gray
-> start camera synchronously
-> start baseline timer
-> generate/load missing grating and ITI raws under gray
-> satisfy baseline/minimum-gray gate
-> play
```

However, RPG conversion while a screen object is open is not yet proven on this hardware.

Implement and log an explicit fallback:

```text
raw_cache_screen_compatibility_fallback = true
```

Fallback order:

```text
build all missing raws before opening screen
-> open screen and display gray
-> start camera
-> wait the full requested baseline
-> play
```

Do not shorten the requested camera baseline because preparation occurred before camera start.

If a persistent cache is already valid, only loading occurs during baseline.

## 27. Drifting-grating events

Protocol fields:

```text
trial_index
orientation_id
bar_orientation_deg
drift_direction_deg
repeat_number
starting_phase_deg
stim_frames
iti_frames
jitter_requested_sec
cache_hash
```

Event types:

```text
prestim_gray_on
camera_start_requested
camera_start_returned
raw_cache_ready
prestim_baseline_start
prestim_baseline_end
session_start
stim_on
iti_on
final_gray
session_end
```

## 28. Drifting-grating outputs

```text
/mnt/hd/<session_id>/
├── <session_id>_planned_sequence.csv
├── <session_id>_event_log.csv
├── <session_id>_metadata.json
├── <session_id>_stimulus_manifest.json
└── video/
```

---

## 29. Remote camera controller

Copy and adapt `remote_camera_control.py` from `vstim_natural` rather than rewriting the camera acquisition commands from scratch.

Preserve:

- explicit `--session-id` support;
- SSH start command;
- remote session directory creation;
- stop command;
- rsync fetch;
- `--remove-source-files` behavior if this remains desired by the laboratory;
- H.264-to-MP4 conversion;
- camera-control event CSV;
- preview/status/manual commands;
- dry-run support.

Change:

- description from `vstim_natural` to `rpi_visual_stimuli`;
- default generated suffix only as a fallback, because experiment runners always pass session ID;
- state file to the namespaced path;
- legacy-state behavior so it does not accidentally consume another repository's last session unless explicitly requested.

Add a safer manual command printed when camera remains running:

```bash
cd ~/rpi_visual_stimuli
python3 remote_camera_control.py stop-fetch
```

Record stop and fetch outcomes in experiment metadata.

---

## 30. CLI options

Both root scripts should support:

```text
--camera
--no-camera
--system-config PATH
--preview-only
--build-cache-only
--dry-run
--test
```

Protocol-specific optional arguments may be added, but interactive prompts remain the normal workflow.

Definitions:

### `--preview-only`

- validate configurations;
- build preview PNGs/contact sheets;
- build trial sequence;
- report duration/memory/disk estimates;
- do not import or call RPG;
- do not use camera;
- do not create a production session.

### `--build-cache-only`

- build and validate the requested persistent cache;
- do not open screen;
- do not start camera;
- print cache path and manifest summary.

### `--dry-run`

- validate prompts/arguments and planned sequence;
- print intended commands and paths;
- no framebuffer, camera, GPIO, or raw conversion side effects unless combined with a specifically documented cache test.

### `--test`

Use short off-animal hardware protocols while preserving the real stimulus frame rate and temporal behavior.

Retinotopy test suggestion:

```text
2-second sweep
5 movement frames per second for geometry stage
or real 15 Hz for timing stage
one repeat
camera optional
```

Drifting-grating test:

```text
2 trials per orientation
16 total trials
0.5-second stimulus
2-Hz temporal frequency
real 60-Hz source frames
short initial/final gray
```

---

## 31. Dependencies

`requirements.txt`:

```text
numpy
Pillow
RPi.GPIO; platform_machine == "armv7l" or platform_machine == "aarch64"
```

`requirements-dev.txt`:

```text
-r requirements.txt
pytest
```

Do not list `rpg` from PyPI unless the exact laboratory package is published there. Document installation from the SjulsonLab repository.

System dependencies:

```text
ffmpeg
rsync
ssh
```

Do not add imageio, OpenCV, PsychoPy, pygame, or a video-encoding Python package only for previews.

Use PNG previews and contact sheets. A preview movie is optional only if it can be created with already-installed tools.

---

## 32. Testing strategy

## 32.1 Test isolation

Pure stimulus-generation, sequence, cache-key, logging, and metadata modules must be importable on a non-Raspberry-Pi computer.

Do not import `rpg` or `RPi.GPIO` at module import time in those modules.

Mock `rpg.convert_raw`, `Screen`, and subprocess calls in unit tests.

## 32.2 Shared core tests

Test:

1. system config parsing and validation;
2. photodiode patch geometry in every supported corner;
3. exact timestamp formatting;
4. display request/return timing wrapper;
5. atomic metadata replacement;
6. CSV header and append behavior;
7. cache hash determinism;
8. cache invalidation after config change;
9. missing/corrupt cache detection;
10. temporary-file cleanup on success and exception;
11. memory and disk preflight messages;
12. camera flag mutual exclusion;
13. interactive camera resolution;
14. baseline gate timer elapsed;
15. baseline satisfied during preparation;
16. user override while still enforcing minimum gray;
17. protocol session naming;
18. namespaced camera state path.

## 32.3 Retinotopy tests

Test:

1. RGB frame size and mode;
2. fresh gray background every frame;
3. photodiode overlay applied last;
4. source-frame count;
5. refreshes-per-source-frame;
6. vertical bands for left/right sweeps;
7. horizontal bands for top/bottom sweeps;
8. constant band width within one pixel;
9. monotonic boundary motion;
10. exact temporal reverse for opposite directions;
11. first and last pair fully outside;
12. no stale trails;
13. two-direction deterministic alternation;
14. balanced four-direction sequence;
15. shuffled-within-repetition balance;
16. cache reuse and rebuild;
17. RAM preflight using actual files;
18. disk preflight peak calculation.

## 32.4 Drifting-grating tests

Test:

1. default config validates;
2. invalid Michelson contrast/mean combination fails;
3. frame shape `(600, 1024, 3)`;
4. `uint8` and values in range;
5. RGB channels equal outside patch;
6. white patch during stimulus;
7. black patch during gray;
8. 0 degrees produces horizontal bars;
9. 90 degrees produces vertical bars;
10. drift direction sign matches documented convention;
11. default source frame count is 30;
12. phase increment is 12 degrees;
13. frame 0 and conceptual frame 30 match within rounding;
14. frame 15 is approximately contrast-inverted around mean;
15. spatial period matches cycles/cm using calibrated dimensions;
16. 640 default trials;
17. 80 per orientation;
18. same seed gives identical order and jitter;
19. different seed normally differs;
20. ITIs are frame-quantized and within range;
21. raw source byte count is exact;
22. previews and contact sheet are created.

## 32.5 Hardware validation stages

### Stage A: gray and photodiode baseline

Before either full protocol:

- open screen;
- display one short gray raw with black patch;
- let the process remain idle;
- verify gray and patch stay visible;
- verify no unintended photodiode transitions;
- verify camera starts only after gray is visible.

### Stage B: retinotopy geometry

Run short sweeps without camera and verify:

- vertical versus horizontal bands;
- entry/exit;
- no trails;
- patch location;
- reverse direction correctness.

### Stage C: drifting-grating geometry

Verify all orientations and labeled previews, especially:

- 0 degrees horizontal;
- 90 degrees vertical;
- 45/135 diagonals;
- drift sign for 0 and 90 degrees;
- spatial period on physical screen.

### Stage D: RPG timing

Confirm:

- mean interframe duration near `16666.7 us` at 60 Hz;
- low standard deviation;
- display call duration near planned duration;
- no obvious judder;
- no load failures.

### Stage E: photodiode recording

Retinotopy:

- one high interval per sweep;
- high throughout sweep;
- low throughout gray;
- planned sweep and gray durations.

Drifting gratings:

- one rising edge per stimulus;
- one falling edge into ITI;
- high for approximately 0.5 seconds;
- ITIs match frame-quantized plan;
- no edges from individual drift frames.

### Stage F: camera integration

For both protocols:

- gray/black patch visible before start command;
- baseline clock begins after command returns;
- early override works;
- minimum gray remains enforced;
- session IDs match;
- video fetches into same session folder;
- manual leave-running option works;
- Ctrl+C reaches camera cleanup prompt;
- metadata accurately records camera state.

### Stage G: complete pilots

Retinotopy pilot:

```text
two directions
20 repeats per direction
20-second sweep
5-second gray
3-minute baseline
```

Drifting-grating pilot:

```text
8 orientations
80 trials each
0.5-second stimulus
0.7 to 1.2-second frame-quantized ITI
3-minute baseline
```

Inspect memory, temperature/throttling, timing logs, photodiode, camera duration, and metadata completeness.

---

## 33. Documentation

## 33.1 Root README

Document:

- repository purpose;
- hardware assumptions;
- installation;
- system configuration;
- two root commands;
- camera prompt and CLI overrides;
- cache locations;
- session output locations;
- photodiode polarity;
- timing interpretation;
- dry-run, preview, cache, and test modes;
- emergency/manual camera stop command;
- warning that `vstim_natural` remains separate and unchanged.

## 33.2 Protocol documentation

`docs/RETINOTOPY.md`:

- direction definitions;
- bar/band geometry;
- two- versus four-direction modes;
- memory requirements;
- persistent cache;
- validation workflow.

`docs/DRIFTING_GRATINGS.md`:

- orientation convention;
- drift direction convention;
- screen calibration;
- spatial/temporal frequency;
- Michelson contrast;
- phase reset;
- trial randomization and ITI quantization;
- validation workflow.

`docs/HARDWARE_VALIDATION.md`:

- staged test checklist;
- photodiode checks;
- camera baseline checks;
- RPG timing limits;
- memory/temperature checks;
- criteria before animal use.

---

## 34. Recommended implementation order

### Phase 0: repository bootstrap

1. Create `hung-lo/rpi_visual_stimuli`.
2. Add layout, README skeleton, requirements, and config.
3. Record source commits in `SOURCE_PROVENANCE.md`.
4. Add CI or local pytest configuration for non-hardware tests.

### Phase 1: shared core

1. timestamps;
2. session paths and naming;
3. event logging;
4. atomic metadata;
5. config loading;
6. photodiode and gray frame;
7. raw streaming/conversion/cache;
8. memory/disk preflight;
9. RPG adapter;
10. GPIO;
11. camera controller copy and namespace changes;
12. camera subprocess wrapper;
13. baseline gate and early-start monitor.

Add unit tests before implementing full protocols.

### Phase 2: drifting gratings first

Implement drifting gratings first because the total loaded movie memory is smaller and it provides a straightforward validation of multi-frame RPG playback.

1. analytical stimulus generator;
2. orientation/drift convention tests;
3. previews;
4. persistent cache;
5. trial sequence and ITI cache;
6. no-camera runner path;
7. hardware smoke test;
8. camera-enabled path;
9. photodiode validation;
10. complete pilot.

### Phase 3: retinotopy

1. direction model;
2. frame generator;
3. preview/contact sheet;
4. streaming conversion;
5. persistent cache;
6. RAM/disk preflight;
7. sequence generation;
8. no-camera path;
9. short geometry test;
10. full-duration timing test;
11. camera path;
12. complete two-direction pilot;
13. only then enable experimental four-direction use.

### Phase 4: cleanup and release

1. verify no duplicated camera/non-camera runners;
2. verify root scripts remain thin;
3. update all docs;
4. run complete test suite;
5. tag the first validated Pi release;
6. record deployed commit in experiment documentation.

---

## 35. Acceptance criteria

The repository is ready when all of the following are true.

### Repository architecture

- [ ] Repository is named `rpi_visual_stimuli`.
- [ ] Only `run_retinotopy.py` and `run_drifting_gratings.py` are experiment entrypoints.
- [ ] Each script asks whether to record the camera.
- [ ] `--camera` and `--no-camera` work and are mutually exclusive.
- [ ] Root run scripts are thin.
- [ ] Shared code lives in the package.
- [ ] `vstim_natural` remains unchanged.
- [ ] New code does not import `vstim_natural` at runtime.

### Shared runtime

- [ ] RPG framebuffer path is used.
- [ ] No X11-dependent display library is added.
- [ ] Photodiode patch is white during stimuli and black during gray.
- [ ] Gray with black patch is visible before camera start.
- [ ] Camera start is synchronous from the experiment runner's perspective.
- [ ] Baseline clock begins after camera start returns.
- [ ] Early-start override cannot violate minimum gray.
- [ ] Camera and stimulus use exactly the same session ID.
- [ ] Post-stimulus stop/fetch behavior works.
- [ ] Camera state file is namespaced.
- [ ] Planned sequence, event log, metadata, and cache manifest are saved.
- [ ] Metadata is updated atomically.
- [ ] Request/return timing and RPG performance fields are logged.
- [ ] Photodiode remains documented as physical timing ground truth.
- [ ] Exceptions leave recoverable partial sessions.

### Retinotopy

- [ ] Two-direction mode reproduces left-to-right azimuth and top-to-bottom elevation sweeps.
- [ ] Left/right sweeps use vertical bands.
- [ ] Top/bottom sweeps use horizontal bands.
- [ ] Every frame begins from fresh gray.
- [ ] Band pair fully enters and exits.
- [ ] Opposite directions are true temporal reverses.
- [ ] Precomputed multi-frame RPG raws are used.
- [ ] Persistent cache is reused.
- [ ] Temporary RGB movies are deleted.
- [ ] Actual raw sizes are used for memory preflight.
- [ ] Four-direction mode never silently overcommits RAM.
- [ ] Complete two-direction pilot passes camera and photodiode validation.

### Drifting gratings

- [ ] Eight default orientations are visually correct.
- [ ] 0 degrees is horizontal and 90 degrees is vertical.
- [ ] Drift direction is explicitly defined and tested.
- [ ] Default sequence has 640 trials and 80 per orientation.
- [ ] Stimulus contains 30 source frames at 60 Hz.
- [ ] Temporal frequency is 2 Hz.
- [ ] Spatial frequency uses verified cycles/cm calibration.
- [ ] Contrast is implemented as validated Michelson contrast.
- [ ] Starting phase resets to zero every trial.
- [ ] ITI is continuous jitter then frame-quantized.
- [ ] One movie is cached per orientation, not per trial.
- [ ] No Python `sleep` loop animates stimulus frames.
- [ ] Complete pilot passes camera and photodiode validation.

---

## 36. Explicit non-goals for the first release

Do not implement yet:

- mismatch-negativity blocks;
- standard/deviant logic;
- optogenetic trial selection;
- NI-card digital tags;
- NI analog laser output;
- automatic Intan recording control;
- direction tuning over 0 to 360 degrees;
- multiple spatial or temporal frequencies in one session;
- contrast tuning;
- circular/Gaussian grating apertures;
- blank trials;
- a third shared-library repository;
- migration of the existing natural-image protocol into this repository.

These can be considered only after both initial protocols are hardware validated.

---

## 37. Suggested commands after implementation

```bash
cd ~/rpi_visual_stimuli

# Normal interactive runs
python3 run_retinotopy.py
python3 run_drifting_gratings.py

# Explicit camera selection
python3 run_retinotopy.py --camera
python3 run_retinotopy.py --no-camera
python3 run_drifting_gratings.py --camera
python3 run_drifting_gratings.py --no-camera

# Preview/configuration checks
python3 run_retinotopy.py --preview-only
python3 run_drifting_gratings.py --preview-only

# Persistent cache generation
python3 run_retinotopy.py --build-cache-only
python3 run_drifting_gratings.py --build-cache-only

# Short hardware tests
python3 run_retinotopy.py --test
python3 run_drifting_gratings.py --test

# Tests
python3 -m pytest -q

# Manual camera cleanup
python3 remote_camera_control.py status
python3 remote_camera_control.py stop-fetch
```

---

## 38. Final Codex instruction

Implement this in small, testable phases. Do not begin by copying both large experiment scripts and editing them independently. First establish the shared timing, cache, baseline, camera, metadata, and RPG adapter modules with tests. Then implement the two protocol runners against those shared components.

When an assumption about RPG behavior cannot be proven from unit tests—especially framebuffer retention after a short gray raw, raw conversion while the screen is open, or actual memory overhead—add an explicit hardware validation step and a logged fallback rather than silently guessing.
