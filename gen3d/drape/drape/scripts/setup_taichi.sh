#!/usr/bin/env bash
# macOS (Apple Silicon) sim env for the taichi engine: gstaichi + numpy only. Run from gen3d/drape.
set -Eeuo pipefail
[ -f pyproject.toml ] && [ -d drape/sim_taichi ] || { echo "run from gen3d/drape" >&2; exit 1; }
PYTHON="${PYTHON:-python3.12}"
[ -d .venv-taichi ] || "$PYTHON" -m venv .venv-taichi
PY=.venv-taichi/bin/python
"$PY" -m pip install -q --upgrade pip
"$PY" -m pip install -q "gstaichi==4.6.0" "numpy==2.5.4"
"$PY" -c "import gstaichi as ti; ti.init(arch=ti.metal); print('metal ok')"
"$PY" -m pip freeze
echo "next: $PY -m drape.sim_taichi.run --scene <name>_scene.npz --arch metal --out <dir>"
