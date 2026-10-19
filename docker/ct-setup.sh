#!/usr/bin/env bash
# One-shot setup for a Debian/Ubuntu LXC (Proxmox). Run as root from anywhere in the repo:
#   bash docker/ct-setup.sh
# Proxmox host side, before running (CT stopped):
#   pct set <ctid> --features nesting=1,keyctl=1   # docker needs both in an unprivileged CT
#   give it >= 4 GB RAM and ~15 GB disk (rembg/onnx + python wheels)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE=(docker compose --project-directory "$ROOT" --profile prod)
cd "$ROOT"

if ! command -v docker >/dev/null || ! docker compose version >/dev/null 2>&1; then
  echo "[seam] installing docker + compose plugin"
  apt-get update -qq && apt-get install -y -qq ca-certificates curl >/dev/null
  curl -fsSL https://get.docker.com | sh
fi

if ! docker run --rm hello-world >/dev/null 2>&1; then
  cat >&2 <<'MSG'
[seam] docker can't start containers in this CT. On the Proxmox host:
  pct set <ctid> --features nesting=1,keyctl=1 && pct reboot <ctid>
If the error mentions "ip_unprivileged_port_start" or apparmor, also add to /etc/pve/lxc/<ctid>.conf:
  lxc.apparmor.profile: unconfined
then reboot the CT and rerun this script.
MSG
  exit 1
fi

[ -f .env ] || { cp .env.example .env; echo "[seam] created .env from .env.example, fill in keys then rerun"; exit 1; }
grep -q '^FAL_KEY=.\+' .env || echo "[seam] warning: FAL_KEY empty in .env"
grep -q '^GEN3D_BACKEND=fal' .env || echo "[seam] warning: GEN3D_BACKEND is not fal, gen3d will serve mock models"
grep -q '^POSTGRES_PASSWORD=.\+' .env || { echo "[seam] set POSTGRES_PASSWORD in .env (openssl rand -hex 24), then rerun"; exit 1; }
grep -q '^POSTGRES_PASSWORD=seam$' .env && echo "[seam] warning: POSTGRES_PASSWORD is the dev default, set a strong one"

mkdir -p data/raw data/clean data/glb data/thumb

"${COMPOSE[@]}" up --build -d

grep -q '^TUNNEL_TOKEN=.\+' .env && { echo "[seam] live on your tunnel's hostname"; exit 0; }
echo "[seam] waiting for tunnel URL..."
for _ in $(seq 60); do
  url=$("${COMPOSE[@]}" logs tunnel 2>/dev/null | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true)
  [ -n "$url" ] && { echo "[seam] live: $url"; exit 0; }
  sleep 2
done
echo "[seam] no tunnel URL yet, check: ${COMPOSE[*]} logs tunnel"
