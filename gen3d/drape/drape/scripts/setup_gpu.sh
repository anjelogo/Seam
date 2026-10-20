#!/usr/bin/env bash
# Provision a CUDA box (Ubuntu 22.04 + CUDA 12, RunPod-style) for the drape PoC. Idempotent.
# Usage: cd gen3d/drape && [VOLUME=/workspace] [CUDA_PATH=...] [FORCE_SMOKE=1] drape/scripts/setup_gpu.sh
set -Eeuo pipefail

STEP="startup"
trap 'echo >&2; echo "SETUP FAILED: step [$STEP] at ${BASH_SOURCE[0]}:${LINENO}: ${BASH_COMMAND}" >&2' ERR

VOLUME="${VOLUME:-/workspace}"
export PATH="$HOME/.local/bin:$PATH"

DRAPE="$PWD"
PY="$DRAPE/.venv/bin/python"
GC="vendor/GarmentCode"
WARP="vendor/NvidiaWarp-GarmentCode"
SMOKE_OUT="$DRAPE/runs/smoke"
SMOKE_LOG="$SMOKE_OUT/smoke.log"

step() { STEP="$1"; echo; echo "==> $1"; }
die() { echo "SETUP FAILED: step [$STEP]: $*" >&2; exit 1; }
have_sim_obj() { [ -n "$(find "$SMOKE_OUT" -name '*_sim.obj' -print -quit 2>/dev/null)" ]; }

# --- 0. checkout sanity ------------------------------------------------------
step "0/8 checkout check ($DRAPE)"
[ -f pyproject.toml ] || die "pyproject.toml missing — run this from the gen3d/drape directory of the repo checkout"
[ -f drape/_repo.py ] || die "drape/_repo.py missing — run this from the gen3d/drape directory of the repo checkout"
if [ -d "$VOLUME" ] && [ -w "$VOLUME" ]; then
    export UV_CACHE_DIR="${UV_CACHE_DIR:-$VOLUME/.cache/uv}"
    mkdir -p "$UV_CACHE_DIR"
    echo "uv cache on volume: $UV_CACHE_DIR"
else
    echo "VOLUME $VOLUME not writable — using the default uv cache"
fi
echo "ok: pyproject.toml + drape/_repo.py present"

# --- 1. GPU ------------------------------------------------------------------
step "1/8 GPU check"
command -v nvidia-smi >/dev/null 2>&1 || die "nvidia-smi not found — this script needs a CUDA GPU box"
GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
[ -n "$GPU_NAME" ] || die "nvidia-smi reported no GPU"
echo "GPU: $GPU_NAME"

# --- 2. system packages ------------------------------------------------------
step "2/8 system packages"
SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "not root and sudo not available"
    SUDO="sudo"
fi
PKGS=(git git-lfs curl ca-certificates build-essential libcairo2 libgl1 libegl1 libosmesa6)
MISSING=()
for p in "${PKGS[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
done
if [ "${#MISSING[@]}" -gt 0 ]; then
    echo "installing: ${MISSING[*]}"
    export DEBIAN_FRONTEND=noninteractive
    $SUDO apt-get update -qq
    $SUDO apt-get install -y --no-install-recommends "${MISSING[@]}"
else
    echo "all ${#PKGS[@]} packages already installed"
fi
git lfs install # must precede the warp clone, else the checkout silently drops warp/
echo "git-lfs: $(git lfs version)"

# --- 3. uv -------------------------------------------------------------------
step "3/8 uv"
if command -v uv >/dev/null 2>&1; then
    echo "uv already installed: $(uv --version)"
else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH (expected \$HOME/.local/bin)"
    echo "uv installed: $(uv --version)"
fi

# --- 4. vendor clones (must precede uv sync: pygarment resolves from vendor/) -
step "4/8 vendor clones"
clone_once() {
    if [ -d "$2/.git" ]; then
        echo "$2 already cloned"
    else
        echo "cloning $1 -> $2"
        git clone --depth 1 "$1" "$2"
    fi
}
mkdir -p vendor
clone_once https://github.com/maria-korosteleva/GarmentCode "$GC"
clone_once https://github.com/maria-korosteleva/NvidiaWarp-GarmentCode "$WARP"
[ -f "$GC/pygarment/__init__.py" ] || die "$GC has no pygarment/ — delete the dir and re-run"
[ -d "$WARP/warp" ] || die "$WARP has no warp/ source tree (git-lfs missing at clone time?) — delete the dir and re-run"

# --- 5. python env -----------------------------------------------------------
step "5/8 uv sync"
uv sync
[ -x "$PY" ] || die "uv sync did not create $PY"
echo "venv: $("$PY" -V)"

# --no-sync keeps uv from pruning the editable warp install (it is not in uv.lock)
UV=(uv run)
if uv run --no-sync python -c pass >/dev/null 2>&1; then
    UV=(uv run --no-sync)
fi

# --- 6. warp fork, built with CUDA -------------------------------------------
step "6/8 warp CUDA build"
CUDA_PATH="${CUDA_PATH:-/usr/local/cuda}"
[ -x "$CUDA_PATH/bin/nvcc" ] || die "CUDA toolkit not found — set CUDA_PATH (looked for $CUDA_PATH/bin/nvcc)"
export CUDA_PATH # must be exported before build_lib.py, else warp silently builds CPU-only
echo "nvcc: $("$CUDA_PATH/bin/nvcc" --version | tail -1)"

warp_device() {
    "${UV[@]}" python -c 'import warp as wp; wp.init(); print("DEVICE=" + str(wp.get_device()))' 2>/dev/null |
        sed -n 's/^DEVICE=//p' | tail -1
}
WARP_DEVICE="$(warp_device || true)"
if printf '%s' "$WARP_DEVICE" | grep -qi cuda; then
    echo "warp already CUDA-enabled (device: $WARP_DEVICE) — skipping build"
else
    (cd "$WARP" && CUDA_PATH="$CUDA_PATH" "$PY" build_lib.py)
    uv pip install -e "$WARP"
    WARP_DEVICE="$(warp_device || true)"
fi
printf '%s' "$WARP_DEVICE" | grep -qi cuda ||
    die "warp reports device '${WARP_DEVICE:-none}' — expected a cuda device (CPU-only build?)"
echo "warp device: $WARP_DEVICE"

# --- 7. upstream smoke sim ---------------------------------------------------
step "7/8 upstream smoke sim"
mkdir -p "$SMOKE_OUT"

# test_garment_sim.py and PathCofig both read ./system.json, so it must sit in vendor/GarmentCode
if [ -f "$GC/system.json" ]; then
    echo "$GC/system.json already present"
else
    "${UV[@]}" python - "$GC" "$SMOKE_OUT" <<'PY'
import json
import sys
from pathlib import Path

gc, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
cfg = json.loads((gc / "system.template.json").read_text())
cfg.update(
    output=str(out),
    sim_configs_path="./assets/Sim_props",
    bodies_default_path="./assets/bodies",
    body_samples_path="",
)
(gc / "system.json").write_text(json.dumps(cfg, indent=2) + "\n")
print("wrote", gc / "system.json")
PY
fi

SPEC="./assets/Patterns/shirt_mean_specification.json"
if [ ! -f "$GC/$SPEC" ]; then
    SPEC="$SMOKE_OUT/smoke_spec/smoke_specification.json"
    if [ -f "$SPEC" ]; then
        echo "generated spec already present: $SPEC"
    else
        echo "upstream spec missing — generating one with MetaGarment"
        "${UV[@]}" python - "$GC" "$SMOKE_OUT/smoke_spec" <<'PY'
import sys
from pathlib import Path

from drape._repo import bootstrap

bootstrap()

import yaml
from assets.bodies.body_params import BodyParameters
from assets.garment_programs.meta_garment import MetaGarment

gc, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
body = BodyParameters(str(gc / "assets" / "bodies" / "mean_all.yaml"))
design = yaml.safe_load((gc / "assets" / "design_params" / "t-shirt.yaml").read_text())["design"]
pattern = MetaGarment("smoke", body, design).assembly()
pattern.serialize(out, to_subfolder=False, with_3d=False, with_text=False, view_ids=False)
print("spec:", out / "smoke_specification.json")
PY
        [ -f "$SPEC" ] || die "spec generation produced no $SPEC"
    fi
fi
echo "spec: $SPEC"

if [ -z "${FORCE_SMOKE:-}" ] && have_sim_obj; then
    SMOKE_SECS="cached"
    echo "upstream smoke sim: already passed (FORCE_SMOKE=1 to re-run)"
else
    t0=$SECONDS
    # PYOPENGL_PLATFORM=egl: pyrender renders headless inside run_sim
    if (cd "$GC" && PYOPENGL_PLATFORM=egl "$PY" test_garment_sim.py -p "$SPEC") 2>&1 | tee "$SMOKE_LOG"; then
        SMOKE_SECS=$((SECONDS - t0))
        echo "upstream smoke sim: ${SMOKE_SECS} s"
    else
        SMOKE_SECS=$((SECONDS - t0))
        if have_sim_obj; then
            echo "WARNING: test_garment_sim.py failed after the sim (headless render); drape.py no-ops the render, continuing"
            SMOKE_SECS="${SMOKE_SECS} (sim ok, render failed)"
            echo "upstream smoke sim: ${SMOKE_SECS} s"
        else
            tail -40 "$SMOKE_LOG" >&2
            die "smoke sim produced no *_sim.obj — see $SMOKE_LOG"
        fi
    fi
fi

# --- 8. summary --------------------------------------------------------------
step "8/8 summary"
echo "SETUP OK"
echo "  GPU:         $GPU_NAME"
echo "  warp device: $WARP_DEVICE"
echo "  smoke sim:   ${SMOKE_SECS} s"
echo "  next:        drape/scripts/run_poc.sh"
