# Hardware Validation

Follow these stages in order before animal use.

## Stage A: Gray And Photodiode Baseline

- Open the RPG screen.
- Display a one-frame gray raw with a black photodiode patch.
- Leave the process idle.
- Verify the gray frame and black patch remain visible after `display_raw()` returns.
- Verify the camera start command is issued only after gray is already visible.

## Stage B: Retinotopy Geometry

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
- Confirm mean interframe duration is near `16666.7 us` at 60 Hz.
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
