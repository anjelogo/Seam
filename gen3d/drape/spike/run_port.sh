#!/usr/bin/env bash
# Spike-only: run the drape pipeline against upstream Apache-2.0 warp instead of the fork,
# by prepending an upstream warp wheel to PYTHONPATH. Touches nothing in vendor/ or .venv.
set -u
export PATH="/root/.local/bin:$PATH"
WP="${WP:-/workspace/spike/wp/1.9.1}"
cd /workspace/seam/gen3d/drape || exit 1
OUT=runs/out_spike_port

echo "=== engine identity under PYTHONPATH override ==="
PYTHONPATH="$WP" uv run --no-sync python -c "import warp; print(warp.config.version, warp.__file__)" 2>&1
echo "=== engine identity WITHOUT override (fork) ==="
uv run --no-sync python -c "import warp; print(warp.config.version, warp.__file__)" 2>&1
echo "=== license metadata of overridden engine ==="
grep -m2 -iE "^(License|Classifier: License)" "$WP"/warp_lang-*.dist-info/METADATA 2>&1

echo ""
echo "=== GAP PROBE: upstream warp (Apache-2.0) ==="
PYTHONPATH="$WP" uv run --no-sync python /workspace/spike/gap_probe.py 2>&1
echo ""
echo "=== GAP PROBE: fork (non-commercial), for contrast ==="
uv run --no-sync python /workspace/spike/gap_probe.py 2>&1

for item in depop_958293311 depop_941190262; do
  echo ""
  echo "=== PORT PATTERN $item ==="
  PYTHONPATH="$WP" uv run --no-sync python -m drape.pattern --inputs runs/inputs --only "$item" \
    --bodies runs/bodies --out "$OUT" 2>&1 | tail -6
  echo "pattern $item rc=$?"
  echo "=== PORT DRAPE $item ==="
  nvidia-smi --query-gpu=memory.used --format=csv,noheader -l 1 > "/workspace/spike/vram_port_${item}.log" 2>&1 &
  VPID=$!
  S=$(date +%s)
  PYTHONPATH="$WP" uv run --no-sync python -m drape.drape --inputs runs/inputs --only "$item" \
    --bodies runs/bodies --out "$OUT" 2>&1
  RC=$?
  E=$(date +%s)
  kill $VPID 2>/dev/null
  echo "drape $item rc=$RC wall=$((E-S))s"
done
echo "=== PORT ATTEMPT DONE ==="
