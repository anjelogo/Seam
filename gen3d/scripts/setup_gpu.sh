#!/usr/bin/env bash
set -euo pipefail

VOLUME="${VOLUME:-/workspace}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONDA_DIR="$VOLUME/miniconda3"
TRELLIS_DIR="$VOLUME/TRELLIS.2"
export HF_HOME="$VOLUME/hf"
export CUDA_HOME="${CUDA_HOME:-/usr/local/cuda}"
export PATH="$CUDA_HOME/bin:$PATH"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

trellis_ok() {
  PYTHONPATH="$TRELLIS_DIR" python -c "import flash_attn, nvdiffrast.torch, nvdiffrec_render, cumesh, flex_gemm, o_voxel, utils3d
from trellis2.pipelines import Trellis2ImageTo3DPipeline"
}

command -v nvidia-smi >/dev/null || die "nvidia-smi not found: this needs an NVIDIA GPU and driver"
nvidia-smi
vram="$(nvidia-smi -i 0 --query-gpu=memory.total --format=csv,noheader,nounits)"
vram="${vram//[^0-9]/}"
if [[ -z "$vram" ]] || ((vram < 23000)); then
  die "GPU 0 has ${vram:-unknown} MiB of VRAM; TRELLIS.2 needs a 24 GB or larger card"
fi
[[ -n "${HF_TOKEN:-}" || -s "$HF_HOME/token" ]] ||
  die "set HF_TOKEN to a Hugging Face token with access to facebook/dinov3-vitl16-pretrain-lvd1689m and briaai/RMBG-2.0 (both gated)"
[[ "$("$CUDA_HOME/bin/nvcc" --version 2>/dev/null)" == *"release 12."* ]] ||
  die "no CUDA 12.x toolkit at CUDA_HOME=$CUDA_HOME; nvcc is needed to build TRELLIS.2's extensions"

SUDO=""
((EUID == 0)) || SUDO=sudo
PKGS=(git curl build-essential libjpeg-dev zlib1g-dev)
if ! dpkg -s "${PKGS[@]}" >/dev/null 2>&1; then
  $SUDO apt-get update
  $SUDO env DEBIAN_FRONTEND=noninteractive apt-get install -y "${PKGS[@]}"
fi

mkdir -p "$VOLUME"
if [[ ! -x "$CONDA_DIR/bin/conda" ]]; then
  curl -fsSL "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-$(uname -m).sh" -o /tmp/miniconda.sh
  bash /tmp/miniconda.sh -b -u -p "$CONDA_DIR"
  rm /tmp/miniconda.sh
fi

[[ -d "$TRELLIS_DIR/.git" ]] || git clone -b main --recursive https://github.com/microsoft/TRELLIS.2.git "$TRELLIS_DIR"
git -C "$TRELLIS_DIR" submodule update --init --recursive

set +u
source "$CONDA_DIR/etc/profile.d/conda.sh"
# not setup.sh --new-env: it pins python 3.10, seam needs 3.11+; conda-forge skips the defaults ToS prompt
[[ -x "$CONDA_DIR/envs/trellis2/bin/python" ]] || conda create -y -n trellis2 --override-channels -c conda-forge python=3.11
conda activate trellis2
set -u

pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
pip install setuptools wheel packaging ninja psutil
# setup.sh's plain pip install builds flash-attn in isolation, where torch is missing
pip install flash-attn==2.7.3 --no-build-isolation

if ! trellis_ok 2>/dev/null; then
  rm -rf /tmp/extensions
  (cd "$TRELLIS_DIR" && set +u && . ./setup.sh --basic --flash-attn --nvdiffrast --nvdiffrec --cumesh --o-voxel --flexgemm) || true
fi

python - "$REPO_DIR" <<'PY'
import subprocess
import sys
import tomllib
from pathlib import Path

repo = Path(sys.argv[1])
deps = tomllib.loads((repo / "gen3d/pyproject.toml").read_text())["project"]["dependencies"]
deps = [d for d in deps if not d.startswith("seam-shared")]
subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", repo / "shared", *deps])
PY
trellis_ok || die "TRELLIS.2 env is incomplete, see the import error above"

python - <<'PY' || die "weight download failed (see above); the HF_TOKEN account needs granted access to facebook/dinov3-vitl16-pretrain-lvd1689m and briaai/RMBG-2.0"
from huggingface_hub import snapshot_download

snapshot_download("microsoft/TRELLIS.2-4B")
snapshot_download("microsoft/TRELLIS-image-large", allow_patterns=["ckpts/ss_dec_conv3d_16l8_fp16.*"])
snapshot_download("facebook/dinov3-vitl16-pretrain-lvd1689m")
snapshot_download("briaai/RMBG-2.0", allow_patterns=["*.json", "*.py", "model.safetensors"])
PY

echo "gen3d GPU setup done"
echo "smoke: VOLUME=$VOLUME bash $REPO_DIR/gen3d/scripts/run_gpu.sh python $REPO_DIR/gen3d/scripts/smoke_local.py <cutout.png>"
echo "serve: VOLUME=$VOLUME bash $REPO_DIR/gen3d/scripts/run_gpu.sh"
