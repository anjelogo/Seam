#!/usr/bin/env bash
# Opt-in .venv-fork with GarmentCode's warp fork (NVIDIA Source Code License: research/evaluation only), never the default install.
# Usage: cd gen3d/drape && [CUDA_PATH=/usr/local/cuda] drape/scripts/setup_fork.sh
set -Eeuo pipefail

STEP="startup"
trap 'echo >&2; echo "SETUP FAILED: step [$STEP] at ${BASH_SOURCE[0]}:${LINENO}: ${BASH_COMMAND}" >&2' ERR
export PATH="$HOME/.local/bin:$PATH"

DRAPE="$PWD"
FORK="vendor/NvidiaWarp-GarmentCode"
ENV="$DRAPE/.venv-fork"
PY="$ENV/bin/python"

step() { STEP="$1"; echo; echo "==> $1"; }
die() { echo "SETUP FAILED: step [$STEP]: $*" >&2; exit 1; }

step "1/4 checks"
[ -f drape/_repo.py ] || die "run this from the gen3d/drape directory"
[ -f vendor/GarmentCode/pygarment/__init__.py ] || die "run drape/scripts/setup_gpu.sh first (it clones GarmentCode)"
command -v uv >/dev/null 2>&1 || die "uv not found, run drape/scripts/setup_gpu.sh first"
CUDA_PATH="${CUDA_PATH:-/usr/local/cuda}"
[ -x "$CUDA_PATH/bin/nvcc" ] || die "the fork builds from source and needs nvcc; set CUDA_PATH (looked for $CUDA_PATH/bin/nvcc)"
export CUDA_PATH
echo "research use only: $FORK is non-commercial (NVIDIA Source Code License)"

step "2/4 clone"
git lfs install # must precede the clone, else the checkout silently drops warp/
if [ -d "$FORK/.git" ]; then
    echo "$FORK already cloned"
else
    git clone --depth 1 https://github.com/maria-korosteleva/NvidiaWarp-GarmentCode "$FORK"
fi
[ -d "$FORK/warp" ] || die "$FORK has no warp/ source tree (git-lfs missing at clone time?), delete it and re-run"

step "3/4 env without newton"
UV_PROJECT_ENVIRONMENT="$ENV" uv sync
[ -x "$PY" ] || die "uv sync did not create $PY"

step "4/4 CUDA build of the fork"
if "$PY" -c 'import warp as wp, warp.sim; wp.init(); assert wp.get_device().is_cuda' >/dev/null 2>&1; then
    echo "fork already built and CUDA-enabled"
else
    chmod +x "$FORK/tools/packman/packman" # tracked as 100644 upstream; build_llvm.py execs it
    (cd "$FORK" && CUDA_PATH="$CUDA_PATH" "$PY" build_lib.py)
    uv pip install --python "$PY" -e "$FORK"
fi
"$PY" -c 'import warp as wp, warp.sim; wp.init(); print("fork warp", wp.__version__, wp.get_device())'

echo
echo "FORK ENV OK (research only): $ENV"
echo "  run: UV_PROJECT_ENVIRONMENT=.venv-fork uv run --no-sync python -m drape.drape --engine fork ..."
