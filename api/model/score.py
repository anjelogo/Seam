# Score the live tagger on gold: python3 -I api/model/score.py data/models/snapshots/items-<date>.jsonl data/models/gold/v1
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gold import COLORS
from material import normalize

items = {r["id"]: r for r in map(json.loads, open(sys.argv[1]))}
gold_dir = Path(sys.argv[2])
strata = {p["id"]: p["stratum"] for p in map(json.loads, open(gold_dir / "sample.jsonl"))}
labels = [l for l in map(json.loads, open(gold_dir / "labels.jsonl")) if l["id"] in strata]


def basic_color(name):
    name = (name or "").lower().replace("gray", "grey").replace("tan", "beige").replace("cream", "beige")
    return next((c for c in COLORS if c in name), "other")


def predict(tags):
    return {
        "material": normalize(tags.get("material")),
        "category": tags.get("category") or "unknown",
        "color": basic_color((tags.get("colors") or [{}])[0].get("name")),
        "usable_for_3d": "yes" if tags.get("usable_for_3d") else "no",
    }


hits = defaultdict(Counter)
pairs = defaultdict(list)
for l in labels:
    pred = predict(items[l["id"]]["tags"])
    for field, want in l.items():
        if field == "id":
            continue
        pairs[field].append((want, pred[field]))
        for key in (field, f"{field} @ {strata[l['id']]}"):
            hits[key]["n"] += 1
            hits[key]["ok"] += want == pred[field]

print(f"gold {gold_dir.name}: {len(labels)} labelled of {len(strata)}\n\naccuracy")
for key in sorted(hits):
    print(f"  {key:45} {hits[key]['ok']:4}/{hits[key]['n']:<4} {100 * hits[key]['ok'] / hits[key]['n']:5.1f}%")

print("\nmaterial per class (precision is skewed up by the leather strata)")
mat = pairs.get("material", [])
for c in sorted({w for w, _ in mat} | {p for _, p in mat}):
    tp = sum(w == p == c for w, p in mat)
    pp, gp = sum(p == c for _, p in mat), sum(w == c for w, _ in mat)
    print(f"  {c:16} prec {tp}/{pp:<4} recall {tp}/{gp:<4}")

print("\ntop material confusions (gold -> tagger)")
for (w, p), n in Counter((w, p) for w, p in mat if w != p).most_common(15):
    print(f"  {n:4}  {w} -> {p}")
