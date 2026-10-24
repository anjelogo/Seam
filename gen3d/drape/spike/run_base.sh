#!/usr/bin/env bash
set -u
export PATH="/root/.local/bin:$PATH"
cd /workspace/seam/gen3d/drape
OUT=runs/out_spike_base
ITEMS="depop_958293311 depop_941190262"
for item in $ITEMS; do
  echo "=== PATTERN $item ==="
  uv run --no-sync python -m drape.pattern --inputs runs/inputs --only "$item" --bodies runs/bodies --out "$OUT" 2>&1
  echo "pattern $item rc=$?"
done
for item in $ITEMS; do
  echo "=== DRAPE $item ==="
  nvidia-smi --query-gpu=memory.used --format=csv,noheader -l 1 > "/workspace/spike/vram_base_${item}.log" 2>&1 &
  VPID=$!
  S=$(date +%s)
  uv run --no-sync python -m drape.drape --inputs runs/inputs --only "$item" --bodies runs/bodies --out "$OUT" 2>&1
  RC=$?
  E=$(date +%s)
  kill $VPID 2>/dev/null
  echo "drape $item rc=$RC wall=$((E-S))s"
done
echo "=== BASELINE DONE ==="
