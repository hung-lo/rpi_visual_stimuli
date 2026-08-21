# Hardware Validation

Follow these stages in order before animal use.

## Stage A: Gray And Photodiode Baseline

- Confirm the Desview OL7 is driven through the 1280 x 720 stimulus framebuffer at 60 Hz.
- Record the active calibration as 15.50 cm x 8.72 cm and the approximate eye-to-screen-center distance as 16.0 cm. Center, azimuth, elevation, yaw, pitch, and roll are assumed zero rather than independently measured.
- Open the RPG screen.
- Display a one-frame gray raw with a black photodiode patch.
- Leave the process idle.
- Verify the gray frame and black patch remain visible after `display_raw()` returns.
- Verify the camera start command is issued only after gray is already visible.

## Stage B: Retinotopy Geometry

- Use flat-screen geometry for downstream visual-angle analysis; do not bake the approximate 51.7 x 30.5 degree coverage into the renderer.
- Run `python3 run_retinotopy.py --test --no-camera`.
- Verify left/right sweeps use vertical bands.
- Verify top/bottom sweeps use horizontal bands.
- Verify the pair fully enters and exits.
- Verify no stale trails appear.
- Verify reverse directions are correct.

## Stage C: Drifting-Grating Geometry

- Run `python3 run_drifting_gratings.py --test --no-camera`.
- Verify 0 degrees is horizontal.
- Verify 90 degrees is vertical.
- Verify 45 and 135 degrees look correct.
- Verify the documented drift sign for 0 and 90 degrees.
- Measure the spatial period on the physical screen after calibration.

## Stage D: RPG Timing

- If RPG timing fields are blank, run `python3 run_retinotopy.py --test --no-camera --test-rpg-return` and compare the reported return shape with the deployed Box RPG installation.
- For drifting gratings, confirm the mean RPG source-frame interval is near `16666.7 us` at the nominal 60-Hz movie-frame rate.
- For retinotopy, expect a source-frame interval near `66666.7 us` because the protocol uses a 15-Hz movement rate with four display refreshes per movement frame. Do not apply the drifting-grating 60-Hz expectation to retinotopy.
- Confirm the standard deviation is low.
- Confirm `display_raw()` call duration is close to the planned raw duration.
- Confirm playback looks smooth and free of obvious judder.
- Treat the photodiode trace as physical display timing; software request/return timestamps and RPG metrics are diagnostic timing references.

## Stage E: Photodiode Recording

Retinotopy:

- one high interval per sweep
- high for the full sweep
- low throughout gray
- planned sweep and gray durations match the log

Drifting gratings:

- one rising edge per stimulus
- one falling edge into ITI
- high for approximately `0.5 sec`
- ITIs match the frame-quantized plan
- no edges from individual drift frames

## Stage F: Camera Integration

- Verify gray with black patch is visible before the start command.
- Verify the baseline clock starts after the start command returns.
- Verify early-start override never violates minimum gray.
- Verify camera and stimulus use the same session ID.
- Verify fetched video lands in the same session folder.
- Verify the leave-running path prints the manual stop-fetch command from this repository.
- Verify `Ctrl+C` still reaches the camera cleanup prompt.
- Verify metadata records camera stop/fetch outcomes accurately.

## Stage G: Complete Pilots

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

Inspect memory usage, temperature or throttling, timing logs, photodiode traces, camera duration, and metadata completeness before animal use.

## Box 151 timing and deployment notes

The observed Box 151 diagnostics were approximately `67064 us` mean interframe for retinotopy and `17257 us` for the short drifting-gratings diagnostic. These are consistent with the protocol targets above; longer runs and photodiode traces are more informative than a short sample.

RPG `start_time` is an integer-second Unix timestamp in the deployed Box 151 RPG. Event metadata therefore also records `display_request_unix_ns` and `display_return_unix_ns` as high-resolution software timestamps. The photodiode transition remains the physical display-timing ground truth.

Run `scripts/box151_smoke_test.sh` on Box 151 after deployment. It performs compile/import/help checks without upgrading the system Python; Box 151 remains the authoritative deployment validation environment.
