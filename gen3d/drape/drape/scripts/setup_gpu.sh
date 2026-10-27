#!/usr/bin/env bash
# Provision a CUDA box (Ubuntu 22.04 + CUDA 12, RunPod-style) for the drape pipeline on Newton. Idempotent.
# Usage: cd gen3d/drape && [VOLUME=/workspace] [FORCE_SMOKE=1] drape/scripts/setup_gpu.sh
set -Eeuo pipefail

STEP="startup"
trap 'echo >&2; echo "SETUP FAILED: step [$STEP] at ${BASH_SOURCE[0]}:${LINENO}: ${BASH_COMMAND}" >&2' ERR

VOLUME="${VOLUME:-/workspace}"
export PATH="$HOME/.local/bin:$PATH"

DRAPE="$PWD"
PY="$DRAPE/.venv/bin/python"
GC="vendor/GarmentCode"
SMOKE_OUT="$DRAPE/runs/smoke"
SMOKE_LOG="$SMOKE_OUT/smoke.log"

step() { STEP="$1"; echo; echo "==> $1"; }
die() { echo "SETUP FAILED: step [$STEP]: $*" >&2; exit 1; }

# --- 0. checkout sanity ------------------------------------------------------
step "0/7 checkout check ($DRAPE)"
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
step "1/7 GPU check"
command -v nvidia-smi >/dev/null 2>&1 || die "nvidia-smi not found — this script needs a CUDA GPU box"
GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || true)"
[ -n "$GPU_NAME" ] || die "nvidia-smi reported no GPU"
echo "GPU: $GPU_NAME"

# --- 2. system packages ------------------------------------------------------
step "2/7 system packages"
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
git lfs install
echo "git-lfs: $(git lfs version)"

# --- 3. uv -------------------------------------------------------------------
step "3/7 uv"
if command -v uv >/dev/null 2>&1; then
    echo "uv already installed: $(uv --version)"
else
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH (expected \$HOME/.local/bin)"
    echo "uv installed: $(uv --version)"
fi

# --- 4. pygarment clone (must precede uv sync: pygarment resolves from vendor/) -
step "4/7 GarmentCode clone"
mkdir -p vendor
if [ -d "$GC/.git" ]; then
    echo "$GC already cloned"
else
    git clone --depth 1 https://github.com/maria-korosteleva/GarmentCode "$GC"
fi
[ -f "$GC/pygarment/__init__.py" ] || die "$GC has no pygarment/ — delete the dir and re-run"

# --- 5. python env: newton + PyPI warp ----------------------------------------
step "5/7 uv sync --extra newton"
uv sync --extra newton
[ -x "$PY" ] || die "uv sync did not create $PY"
echo "venv: $("$PY" -V)"

# --- 6. engine check ---------------------------------------------------------
step "6/7 warp + newton on the GPU"
IDENT="$("$PY" -c 'import warp as wp, newton; wp.init(); print(wp.__file__, wp.__version__, newton.__version__, wp.get_device())' 2>/dev/null | tail -1)"
echo "$IDENT"
printf '%s' "$IDENT" | grep -q "site-packages/warp" || die "warp does not resolve to the PyPI wheel"
printf '%s' "$IDENT" | grep -qi cuda || die "warp reports no cuda device"

# --- 7. newton smoke sim -----------------------------------------------------
step "7/7 newton smoke sim"
mkdir -p "$SMOKE_OUT"
if [ -z "${FORCE_SMOKE:-}" ] && [ -f "$SMOKE_OUT/newton_ok" ]; then
    SMOKE_SECS="cached"
    echo "newton smoke sim: already passed (FORCE_SMOKE=1 to re-run)"
else
    t0=$SECONDS
    "$PY" -m newton.examples cloth_hanging --viewer null --num-frames 100 --solver xpbd --test 2>&1 | tee "$SMOKE_LOG" ||
        die "newton cloth example failed — see $SMOKE_LOG"
    SMOKE_SECS=$((SECONDS - t0))
    touch "$SMOKE_OUT/newton_ok"
    echo "newton smoke sim: ${SMOKE_SECS} s"
fi

echo
echo "SETUP OK"
echo "  GPU:        $GPU_NAME"
echo "  engine:     $IDENT"
echo "  smoke sim:  ${SMOKE_SECS} s"
echo "  next:       uv run --no-sync python -m drape.drape --inputs runs/inputs --only <item>"
echo "  fork (research only, opt-in): drape/scripts/setup_fork.sh"
