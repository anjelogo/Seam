#!/usr/bin/env bash
# run_gpu.sh [cmd...]: serve gen3d on :8001, or run cmd in the same env
set -euo pipefail

VOLUME="${VOLUME:-/workspace}"
GEN3D_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

set +u
source "$VOLUME/miniconda3/etc/profile.d/conda.sh"
conda activate trellis2
set -u

# setup_gpu.sh cached every weight, so serving never calls the hub
export GEN3D_BACKEND=local HF_HOME="$VOLUME/hf" HF_HUB_OFFLINE=1
export PYTHONPATH="$VOLUME/TRELLIS.2${PYTHONPATH:+:$PYTHONPATH}"

if (($#)); then
  exec "$@"
fi
cd "$GEN3D_DIR"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
