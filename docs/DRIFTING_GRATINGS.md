# Drifting Gratings

## Orientation Convention

`bar_orientation_deg` is an unoriented line angle modulo 180 degrees, measured counterclockwise from the positive x-axis:

- `0` degrees: horizontal bars
- `90` degrees: vertical bars

The grating carrier is perpendicular to the visible bars.

## Drift Direction Convention

The implementation uses increasing temporal phase:

```python
phase_rad = (
    np.deg2rad(starting_phase_deg)
    + 2.0 * np.pi * temporal_frequency_hz
      * frame_index / refresh_rate_hz
)
```

With this sign convention, the apparent drift direction is:

```python
drift_direction_deg = (bar_orientation_deg - 90.0) % 360.0
```

The repository includes previews and tests that explicitly check the 0-degree and 90-degree sign convention rather than relying on intuition.

## Screen Calibration

Spatial frequency in cycles/cm is meaningful only after the visible monitor width and height in `config/system_config.json` have been measured on the actual display.

The active-area calibration for the Desview OL7 is 15.50 cm wide by 8.72 cm high. The stimulus framebuffer is 1280 x 720 at 60 Hz, preserving the panel's 16:9 aspect ratio while keeping raw and RAM costs below 1920 x 1080. The approximate eye-to-screen-center distance is 16.0 cm; viewer centering and orientation values are assumptions stored in session metadata.

## Spatial Frequency, Temporal Frequency, And Contrast

Defaults:

- spatial frequency: `0.2 cycles/cm`
- temporal frequency: `2.0 Hz`
- mean luminance: `0.5`
- Michelson contrast: `1.0`
- starting phase: `0.0 degrees`

Luminance is defined as:

```python
luminance = mean_luminance * (1.0 + contrast * sinusoid)
```

Configurations that would require clipping are rejected.

## Phase Reset, Randomization, And ITI Quantization

One cached movie is reused per orientation, so phase resets to zero every trial.

Trial generation:

- create `trials_per_orientation` entries for each orientation
- globally shuffle the full trial list with a local RNG
- draw continuous ITI jitter from `[0, jitter_max)`
- quantize ITI to the nearest monitor frame

The jitter sequence affects the trial plan and gray-raw set, but not the orientation stimulus cache hash.

## Validation Workflow

1. Run `python3 run_drifting_gratings.py --preview-only` and inspect the per-orientation PNGs plus contact sheet.
2. Run `python3 run_drifting_gratings.py --test --no-camera`.
3. Verify that 0 degrees is horizontal and 90 degrees is vertical on the physical screen.
4. Confirm the photodiode is white during stimulus and black during gray.
5. Confirm ITIs match the frame-quantized plan and that no individual drift frames create photodiode edges.
