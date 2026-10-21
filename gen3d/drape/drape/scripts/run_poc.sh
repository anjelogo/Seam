#!/usr/bin/env bash
# Batch-run the drape PoC over every input item, then the sizes/layers experiments.
# Usage: cd gen3d/drape && drape/scripts/run_poc.sh [INPUTS_DIR=runs/inputs] [OUT_DIR=runs/out]
set -Eeuo pipefail

STEP="startup"
trap 'echo >&2; echo "RUN FAILED: step [$STEP] at ${BASH_SOURCE[0]}:${LINENO}: ${BASH_COMMAND}" >&2' ERR

export PATH="$HOME/.local/bin:$PATH"

INPUTS_DIR="${1:-runs/inputs}"
OUT_DIR="${2:-runs/out}"
BODIES_DIR="runs/bodies"
WEARER="wearer_masc"

step() { STEP="$1"; echo; echo "==> $1"; }
die() { echo "RUN FAILED: step [$STEP]: $*" >&2; exit 1; }

step "preflight"
[ -f pyproject.toml ] || die "pyproject.toml missing — run this from the gen3d/drape directory"
[ -f drape/_repo.py ] || die "drape/_repo.py missing — run this from the gen3d/drape directory"
[ -d "$INPUTS_DIR" ] || die "inputs dir $INPUTS_DIR not found — run 'uv run python -m drape.inputs' first"
mkdir -p "$OUT_DIR" "$BODIES_DIR"

# --no-sync keeps uv from pruning the editable warp install (it is not in uv.lock)
UV=(uv run)
if uv run --no-sync python -c pass >/dev/null 2>&1; then
    UV=(uv run --no-sync)
fi
echo "inputs=$INPUTS_DIR out=$OUT_DIR bodies=$BODIES_DIR uv='${UV[*]}'"

TOTAL_START=$SECONDS

step "bodies"
if [ -f "$BODIES_DIR/$WEARER.yaml" ]; then
    echo "$WEARER already generated"
else
    "${UV[@]}" python -m drape.body --base masc --name "$WEARER" ||
        die "drape.body failed — generate the wearer manually: uv run python -m drape.body --base masc --name $WEARER"
fi
[ -f "$BODIES_DIR/$WEARER.yaml" ] ||
    die "$BODIES_DIR/$WEARER.yaml still missing — run: uv run python -m drape.body --base masc --name $WEARER"
if [ -f "$BODIES_DIR/wearer_fem.yaml" ]; then
    echo "wearer_fem already generated"
else
    "${UV[@]}" python -m drape.body --base fem --name wearer_fem ||
        echo "wearer_fem generation failed (optional — the PoC drapes on $WEARER)"
fi

step "collect items"
ITEMS=()
for d in "$INPUTS_DIR"/*/; do
    [ -f "$d/item.json" ] || continue
    ITEMS+=("$(basename "$d")")
done
[ "${#ITEMS[@]}" -gt 0 ] || die "no item dirs with item.json under $INPUTS_DIR"
echo "${#ITEMS[@]} items: ${ITEMS[*]}"

step "per-item pattern + drape"
OK=0
FAILED=()
for id in "${ITEMS[@]}"; do
    echo
    echo "-- $id"
    item_start=$SECONDS
    item_ok=1
    "${UV[@]}" python -m drape.pattern \
        --inputs "$INPUTS_DIR" --bodies "$BODIES_DIR" --out "$OUT_DIR" --only "$id" ||
        { echo "pattern failed for $id"; item_ok=0; }
    if [ "$item_ok" -eq 1 ]; then
        "${UV[@]}" python -m drape.drape \
            --inputs "$INPUTS_DIR" --bodies "$BODIES_DIR" --out "$OUT_DIR" \
            --wearer "$WEARER" --only "$id" ||
            { echo "drape failed for $id"; item_ok=0; }
    fi
    if [ "$item_ok" -eq 1 ]; then
        OK=$((OK + 1))
    else
        FAILED+=("$id")
    fi
    echo "-- $id: $((SECONDS - item_start)) s"
done

step "experiments"
for exp in sizes layers; do
    exp_start=$SECONDS
    "${UV[@]}" python -m drape.drape --experiment "$exp" \
        --inputs "$INPUTS_DIR" --bodies "$BODIES_DIR" --out "$OUT_DIR" --wearer "$WEARER" ||
        echo "experiment $exp failed (module may not exist yet)"
    echo "-- experiment $exp: $((SECONDS - exp_start)) s"
done

step "texture / export / bind"
"${UV[@]}" python -m drape.texture --inputs "$INPUTS_DIR" --out "$OUT_DIR" ||
    echo "texture failed (module may not exist yet)"
"${UV[@]}" python -m drape.export --inputs "$INPUTS_DIR" --out "$OUT_DIR" ||
    echo "export failed (module may not exist yet)"
"${UV[@]}" python -m drape.bind --inputs "$INPUTS_DIR" --out "$OUT_DIR" ||
    echo "bind failed (module may not exist yet)"

step "summary"
TOTAL=$((SECONDS - TOTAL_START))
if [ "${#FAILED[@]}" -gt 0 ]; then
    echo "failed items: ${FAILED[*]}"
fi
echo "RUN DONE: ${OK}/${#ITEMS[@]} items draped, ${TOTAL} s total, artifacts in $OUT_DIR"
[ "$OK" -gt 0 ] || die "every item failed — see the log above"
