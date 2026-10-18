#!/usr/bin/env bash
set -euo pipefail

# work on a copy so container installs never touch the host checkout mounted at /src
rm -rf /app && mkdir -p /app
tar -C /src --exclude=./.git --exclude=./.venv --exclude=./data --exclude=./web/node_modules --exclude=./web/dist \
  --exclude='*/__pycache__' -cf - . | tar -C /app -xf -
cd /app

echo "[seam] installing deps (first start takes ~2 min, ports open after)"
# shortcut: master's uv.lock doesn't parse and perceptron needs pillow<12; drop once the lock is fixed
sed -i 's/"pillow>=13.0.0"/"pillow>=11"/' gen3d/pyproject.toml
uv lock -q
uv sync --all-packages --frozen -q
(cd web && npm ci --no-audit --no-fund --loglevel=error)

(cd api && exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000) &
(cd gen3d && exec uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8001) &
(cd web && exec npx vite --host 0.0.0.0 --port 5273 --strictPort) &
until curl -sf -o /dev/null localhost:8000/health && curl -sf -o /dev/null localhost:8001/health && curl -sf -o /dev/null localhost:5273; do sleep 1; done
echo "[seam] ready: http://localhost:5273"
wait
