#!/usr/bin/env bash
set -euo pipefail

# Box 151 is validated with its existing Python 3.7 environment.
python3 -m compileall -q rpi_visual_stimuli
python3 -c "import rpi_visual_stimuli"
python3 run_retinotopy.py --help >/dev/null
python3 run_drifting_gratings.py --help >/dev/null
echo "Box 151 smoke test passed."
