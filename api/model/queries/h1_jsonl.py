# H1 on an /admin export: python3 api/model/queries/h1_jsonl.py data/models/snapshots/items-<date>.jsonl
import json
import sys
from collections import Counter, defaultdict

rows = [json.loads(line) for line in open(sys.argv[1])]
print(f"rows {len(rows)}  status {dict(Counter(r['status'] for r in rows))}  tagged {sum(r['tags'] is not None for r in rows)}")

groups = defaultdict(lambda: [0, 0, 0, 0])
materials = Counter()
for r in rows:
    t = r["tags"]
    # all statuses: the 10-28 export is 100% gone (scraping stopped 10-24)
    if not t:
        continue
    l = r["listing"] or {}
    mat = (t.get("material") or "").lower()
    materials[mat or "<none>"] += 1
    tag_l = "leather" in mat or t.get("category") == "leather_jacket"
    txt_l = "leather" in f"{l.get('title') or ''} {l.get('description') or ''}".lower()
    for key in [(r["source"], t.get("slot")), (r["source"], "ALL"), ("ALL", t.get("slot")), ("ALL", "ALL")]:
        g = groups[key]
        g[0] += 1; g[1] += tag_l; g[2] += tag_l and not txt_l; g[3] += txt_l and not tag_l

print(f"\n{'source':10}{'slot':10}{'n':>6}{'tag%':>7}{'tag_only':>10}{'text_only':>10}")
for (src, slot), (n, tl, to, xo) in sorted(groups.items(), key=lambda kv: (kv[0][0] == "ALL", kv[0][0], kv[0][1] == "ALL", str(kv[0][1]))):
    print(f"{src:10}{str(slot):10}{n:6}{100 * tl / n:7.1f}{to:10}{xo:10}")

print("\nmaterial values (tagged):")
for m, c in materials.most_common():
    print(f"{c:6}  {m}")
