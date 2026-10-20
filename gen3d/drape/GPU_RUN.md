# GPU run playbook (hand this to a fresh agent session)

Goal: run the drape PoC's GPU stage on a Runpod pod and fill the TBD sections of
gen3d/drape/RESULTS.md. Read RESULTS.md first for full context. Everything below assumes the
repo worktree at /Users/anjelo/Github/Seam-drape-poc on branch anjelo/drape-poc.

## State you inherit

- Runpod MCP server: connected + OAuth'd (tools appear as `runpod_*`; `pod-deploy` /
  `lifecycle-crud` / `pod-doctor` journey skills installed in ~/.agents/skills).
- Local artifacts ready to ship: gen3d/drape/runs/inputs/ (4 items), runs/bodies/ (wearer +
  size bodies + ggg_body_segmentation.json). Both are gitignored — they must be rsynced, not
  pulled via git.
- gen3d/drape/drape/scripts/setup_gpu.sh and run_poc.sh are committed and shellcheck-clean.
- Local mac quirks that do NOT apply on the pod: the warp CPU segfault, the Darwin
  frame-timeout patch. On the pod everything runs the upstream CUDA path.
- Always invoke python as `uv run --no-sync python ...` from gen3d/drape (plain `uv run`
  can prune the editable warp install).
- SSH key: ~/.ssh/id_ed25519 (public key at ~/.ssh/id_ed25519.pub).

## 1. Create the pod (runpod MCP, pod-deploy journey)

- Catalog read first; pick the cheapest available of 1x RTX 4090 / RTX 3090 (24 GB is plenty;
  paper baseline was a 3090 at ~30 s/garment). Quote the price from the read.
- create-pod: name `seam-drape-poc`; gpu.minCudaVersion "12.8"; image
  `runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04` (any runpod/pytorch *-devel-*
  cuda12.x ubuntu22.04 tag works — it must have nvcc); containerDiskInGb 40; volumeInGb 50 at
  /workspace; ports include "22/tcp"; env PUBLIC_KEY = contents of ~/.ssh/id_ed25519.pub.
- Wait for RUNNING, get-pod, extract public IP + external port for 22/tcp.
- ONE pod only. If create errors, report verbatim; do not blind-retry.

## 2. Ship the code + inputs

```sh
cd /Users/anjelo/Github/Seam-drape-poc
rsync -az -e "ssh -p PORT -i ~/.ssh/id_ed25519" --exclude .venv --exclude vendor \
  --exclude runs/out --exclude .git gen3d shared assets pyproject.toml .python-version \
  root@IP:/workspace/seam/
```

(runs/inputs and runs/bodies ride along inside gen3d/drape/runs/. The repo layout matters:
drape/_repo.py resolves gen3d/../shared and ../assets relative to itself.)

## 3. Provision + run (on the pod, via ssh)

```sh
ssh root@IP -p PORT -i ~/.ssh/id_ed25519
cd /workspace/seam/gen3d/drape
bash drape/scripts/setup_gpu.sh    # apt deps + git-lfs BEFORE clones + uv sync + warp CUDA build + upstream smoke (prints seconds)
bash drape/scripts/run_poc.sh      # all 4 items + XS/M/XL size experiment + tee->hoodie layer test + texture/export/bind on real sim objs
```

Expected wall time: setup ~10-15 min, run ~5-15 min GPU. Both scripts are idempotent and die
loudly naming the failed step. If a sim fails, `pod-doctor` journey + runs/out/timings.json
fails field. For the binding-vs-redrape number:

```sh
uv run --no-sync python -m drape.drape --only grailed_108767954 --wearer wearer_masc_183 --size L --out runs/out_redrape08   # after generating a height-0.8 body: uv run --no-sync python -m drape.body --base masc --name wearer_masc_h08 --sliders height=0.8
uv run --no-sync python -m drape.bind --only grailed_108767954 --push height=0.8 --compare <path to that _sim.obj>
```

## 4. Bring results home + finish

```sh
rsync -az -e "ssh -p PORT -i ~/.ssh/id_ed25519" root@IP:/workspace/seam/gen3d/drape/runs/out/ \
  /Users/anjelo/Github/Seam-drape-poc/gen3d/drape/runs/out/
cd gen3d/drape && uv run --no-sync python viewer/build_manifest.py
# re-shoot: cd repo root; python3 -m http.server 8808; open /gen3d/drape/viewer/index.html
# (viewer exposes window.__poc.set(item,mode,size) + setView(azimuthDeg) for scripted shots
#  to runs/out/shots/ — same 16-shot matrix as the committed ones)
```

Then fill RESULTS.md's "TBD after run_poc.sh" + size-experiment + verdict-quality lines with
numbers from runs/out/timings.json (sim_s, vram_mb, device, fails) and the new shots, commit
`docs(drape): gpu results` on anjelo/drape-poc, and STOP the pod (stop, not delete — or
delete if the user says done; it was created by that session so stopping it is in scope).

## Cost guardrail

4090 ≈ $0.35-0.70/h. The whole run fits in well under 1 hour. Stop the pod when done.
