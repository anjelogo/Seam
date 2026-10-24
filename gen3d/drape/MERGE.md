# Merging anjelo/tee-neck into master

## What the merge brings

The drape work is one linear chain of branches, each cut from the one before, and none of them has
reached master. Merging `anjelo/tee-neck` brings all six:

| branch | tip | adds |
|---|---|---|
| anjelo/drape-poc | 27a86cd | sewing-pattern + cloth-sim PoC in gen3d/drape (its own uv package) |
| anjelo/texture-v2 | 9c0fa4f | texturing in sewing-pattern space |
| anjelo/texture-v3 | 5a56ad7 | texture v3; wider, flatter mannequin shoulders (c47caeb) |
| anjelo/tee-collar | aa20916 | smooth arm-to-trunk shoulder join (5fe121c); tee collar experiments |
| anjelo/tee-fix | 977cdc1 | body-yaml datum fix (tees sit on the shoulders), stretch-on rib band |
| anjelo/tee-neck | this branch, 7 commits on tee-fix | tee body-length prior, clean contact-sheet renders, crew-neck V traced (the arc-band fix is documented, not shipped) |

Every branch tip above is an ancestor of `anjelo/tee-neck` (`git merge-base --is-ancestor`), and so is
origin/master (cfa9000): the branch is 49 commits ahead (this checklist included) and 0 behind.

## Conflict check (dry run, writes nothing)

```sh
git fetch origin
git merge-tree --write-tree origin/master anjelo/tee-neck
```

Result (2026-10-24 02:39 UTC, at 9bba75d; this commit only adds MERGE.md): exit 0, tree 5ea28f9, no
conflicting files. master has not moved since the chain branched, so the merge cannot conflict;
`--no-ff` keeps one merge commit for the whole chain.

## What changes for production

- **Avatar and template GLBs are re-exported with the new shoulders.** `assets/avatar_masc.glb`,
  `assets/avatar_fem.glb`, all 22 `assets/templates/*.glb` and `assets/anchors.json` come from the edited
  `gen3d/app/mannequin/params.py` (c47caeb wider/flatter shoulders, 5fe121c arm-to-trunk join). Morph
  target names and anchor keys are unchanged, so the web loads them as before.
- **Templates need a rebake.** Item textures baked onto the old templates no longer line up. After the
  merge: `cd gen3d && uv run python -m app.bake --ready`, repeated until it prints "nothing to rebake".
- **Nothing in gen3d/drape is wired into the prod pipeline.** No api, web, worker or gen3d server code
  imports it; it is a separate uv package that is run by hand. web/, api/ and shared/ are untouched by
  the whole chain.
- **The cloth sim is non-commercial.** The NvidiaWarp-GarmentCode fork is under the NVIDIA Source Code
  License (research/eval only), so the drape path must not serve users until it is ported to Newton
  (Apache-2.0); see LICENSE_SPIKE.md. Pattern generation (GarmentCode, MIT) is clean.

## Files that must not reach master

Checked with `git diff --stat origin/master...HEAD` plus the blob size of every added or modified file
(321 files, this checklist included):

| rule | offenders |
|---|---|
| over 20 MB | none (largest: 2.9 MB, `gen3d/drape/runs/out/shots/texture_v3/fixes/tint_mudwash_back_seed.png`) |
| run outputs outside `gen3d/drape/runs/out/shots/` | none (`runs/*` is gitignored; only shots are tracked) |
| vendor build artifacts | none (`gen3d/drape/vendor/` is gitignored, 0 tracked files) |

## Merge (the human runs this)

Either open a PR (https://github.com/anjelogo/Seam/compare/master...anjelo/tee-neck) and merge it with
"Create a merge commit", or locally:

```sh
git checkout master
git pull --ff-only origin master
git merge --no-ff anjelo/tee-neck
git push origin master
```

## Post-merge smoke check

1. Web builds: `cd web && npm ci && npm run build` exits 0 (`tsc && vite build`).
2. Avatar loads: `make dev`, open the web app; the mannequin renders with the new shoulders and the body
   sliders still morph it.
3. Templates rebake: `cd gen3d && uv run python -m app.bake --ready` until "nothing to rebake".
4. Drape viewer: from the repo root `python3 -m http.server 8808`, then open
   http://localhost:8808/gen3d/drape/viewer/index.html?out=runs/out_tee_fix; the tees load with the new
   necklines. `runs/` is gitignored, so this only works on the machine that holds the run outputs.
