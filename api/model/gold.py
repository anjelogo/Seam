# Gold set v1 sample + labelling page: python3 -I api/model/gold.py data/models/snapshots/items-<date>.jsonl
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from material import VOCAB, normalize

OUT = Path("data/models/gold/v1")
SLOT_QUOTA = {"top": 50, "bottom": 50, "outer": 50, "shoes": 40, "onepiece": 5, "accessory": 5}
CATEGORIES = ["tee", "longsleeve", "tank", "button_up", "polo", "sweater", "hoodie", "sweatshirt", "jacket", "denim_jacket",
              "leather_jacket", "coat", "vest", "jeans", "pants", "cargo", "shorts", "skirt", "dress", "jumpsuit", "sneakers",
              "boots", "shoes_other", "hat", "bag", "accessory_other", "unknown"]
COLORS = ["black", "white", "grey", "brown", "beige", "red", "orange", "yellow", "green", "blue", "navy", "purple", "pink", "silver", "gold", "multi"]


def take(stratum, pool, n, picked, seen, rng):
    pool = [r for r in pool if r["id"] not in seen]
    for r in rng.sample(pool, min(n, len(pool))):
        seen.add(r["id"])
        picked.append({"id": r["id"], "stratum": stratum})


if __name__ == "__main__":
    rows = [r for r in map(json.loads, open(sys.argv[1])) if r["tags"]]
    for r in rows:
        l = r["listing"] or {}
        r["_mat"] = normalize(r["tags"].get("material"))
        r["_txt_leather"] = "leather" in f"{l.get('title') or ''} {l.get('description') or ''}".lower()
    leathery = {"leather", "patent_leather", "suede"}

    rng = random.Random(20261028)
    picked, seen = [], set()
    take("h2_shoe_leather_no_text", [r for r in rows if r["tags"].get("slot") == "shoes" and r["_mat"] in leathery and not r["_txt_leather"]], 60, picked, seen, rng)
    take("leather_tagged", [r for r in rows if r["tags"].get("slot") != "shoes" and (r["_mat"] in leathery or r["tags"].get("category") == "leather_jacket")], 40, picked, seen, rng)
    for slot, n in SLOT_QUOTA.items():
        take(f"slot_{slot}", [r for r in rows if r["tags"].get("slot") == slot], n, picked, seen, rng)
    assert len(picked) == len({p["id"] for p in picked})

    by_id = {r["id"]: r for r in rows}
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "sample.jsonl", "w") as f:
        for p in picked:
            f.write(json.dumps(p) + "\n")

    items = [{"id": p["id"], "title": by_id[p["id"]]["listing"].get("title"), "desc": by_id[p["id"]]["listing"].get("description"),
              "url": by_id[p["id"]]["url"], "images": [i["url"] for i in by_id[p["id"]]["listing"].get("images") or []]} for p in picked]
    page = (Path(__file__).parent / "gold_label.html").read_text()
    for key, value in {"ITEMS": items, "MATERIALS": VOCAB, "CATEGORIES": CATEGORIES, "COLORS": COLORS}.items():
        page = page.replace(f"/*{key}*/[]", json.dumps(value).replace("</", "<\\/"))
    (OUT / "label.html").write_text(page)
    print(f"{len(picked)} items -> {OUT}/sample.jsonl, open {OUT}/label.html")
