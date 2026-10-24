#!/usr/bin/env bash
set -u
cd /workspace/spike
cat > /workspace/spike/probe_one.py <<'PY'
import sys
try:
    import warp as wp
except Exception as e:
    print(f"IMPORT_WARP_FAIL: {type(e).__name__}: {e}"); sys.exit(0)
print(f"warp version: {wp.config.version}")
try:
    import warp.sim
except Exception as e:
    print(f"IMPORT_WARP_SIM_FAIL: {type(e).__name__}: {e}"); sys.exit(0)
need = ["ModelBuilder","XPBDIntegrator","Mesh","collide","Model","render"]
print("warp.sim OK -> " + ", ".join(f"{n}={hasattr(warp.sim,n)}" for n in need))
PY
for v in 1.18.0 1.15.0 1.12.0 1.10.1 1.9.1 1.8.1 1.7.2; do
  echo "##### warp-lang==$v #####"
  d="/workspace/spike/wp/$v"
  rm -rf "$d"; mkdir -p "$d"
  python3 -m pip install --quiet --no-deps --target "$d" "warp-lang==$v" > "/workspace/spike/wp/pip_$v.log" 2>&1
  echo "  pip rc=$?"
  PYTHONPATH="$d" python3 /workspace/spike/probe_one.py 2>&1 | sed "s/^/  /"
done
echo "##### PROBE DONE #####"
