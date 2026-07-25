# Retinotopy

## Direction Definitions

- `left_to_right`: azimuth sweep using vertical bands that move along the x-axis
- `right_to_left`: exact temporal reverse of `left_to_right`
- `top_to_bottom`: elevation sweep using horizontal bands that move along the y-axis
- `bottom_to_top`: exact temporal reverse of `top_to_bottom`

The event log always records the exact direction, not only `Azimuth` or `Elevation`.

## Band Geometry

Each movement frame begins from a fresh mid-gray RGB canvas.

The stimulus is an adjacent black/white band pair. Each individual band has width:

```python
round(relevant_screen_dimension * bar_width_fraction)
```

The black band leads the white band in screen coordinates:

- left/right sweeps: black on the left, white on the right
- top/bottom sweeps: black above, white below

The pair begins fully outside the screen, traverses the display, and ends fully outside the screen. The photodiode patch is applied last and stays white for the full sweep.

## Sequence Modes

Two-direction default:

```text
left_to_right
top_to_bottom
left_to_right
top_to_bottom
...
```

Four-direction fixed order:

```text
left_to_right
right_to_left
top_to_bottom
bottom_to_top
...
```

Shuffled mode shuffles within each repetition so every enabled direction appears exactly once per repetition.

## Memory And Cache

Persistent retinotopy cache:

```text
/mnt/hd/vstim_cache/retinotopy/<cache_hash>/
```

The cache stores converted sweep raws and the inter-sweep gray raw. Session folders copy only the cache manifest and log the absolute cache paths.

Memory checks use actual converted raw file sizes plus:

- 15% overhead factor
- 768 MiB safety margin

Disk checks for cache generation use the estimated peak of one temporary RGB source movie plus one converted raw, with a 1 GiB free-space margin.

## Validation Workflow

1. Run `python3 run_retinotopy.py --preview-only` and inspect the preview contact sheet.
2. Run `python3 run_retinotopy.py --test --no-camera` for short geometry checks.
3. Verify vertical versus horizontal band orientation, entry/exit, and absence of trails.
4. Confirm the one-frame gray raw retains a black photodiode patch while the process remains idle.
5. Validate two-direction mode first before enabling experimental four-direction use.
