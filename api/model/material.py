# Material vocab v1: python3 api/model/material.py data/models/snapshots/items-<date>.jsonl
import json
import re
import sys
from collections import Counter

# order matters: first match wins, so specific beats general (faux leather before leather)
RULES = [
    ("faux_leather", r"faux.?leather|pleather|vegan.?leather|synthetic.?leather|man.?made.?leather|pu leather|leather.?(like|look)|polyurethane|\bpvc\b|vinyl"),
    ("patent_leather", r"patent"),
    ("faux_suede", r"faux.?suede|suede.?(ish|like)"),
    ("suede", r"suede|nubuck"),
    ("leather", r"leather|cowhide|pony hair"),
    ("faux_fur", r"faux.?(fur|shearling)|synthetic.?fur"),
    ("fur_shearling", r"\bfur\b|shearling"),
    ("denim", r"denim"),
    ("corduroy", r"corduroy"),
    ("canvas", r"canvas|\bduck\b|duck cotton"),
    ("fleece", r"fleece|sherpa|sweatshirt|terry"),
    ("velvet", r"velvet|velour"),
    ("wool", r"wool|cashmere|merino|tweed|flannel"),
    ("silk_satin", r"silk|satin|sateen|chiffon|crepe"),
    ("linen", r"linen|ramie|hemp|seersucker"),
    ("down_puffer", r"\bdown\b|puffer|kapok|insulation"),
    ("lace", r"lace"),
    ("knit", r"knit|rib|waffle|thermal|jersey|crochet|ponte|tricot"),
    ("mesh", r"mesh"),
    ("nylon", r"nylon|ripstop|cordura|gore-tex|softshell|soft shell|windbreaker|polyamide"),
    ("rubber_foam", r"rubber|croslite|foam|jelly"),
    ("cotton_blend", r"cotton.?blend|cotton[,/& -]+(poly|nylon|viscose|elastane|spandex|modal)|(poly|polyester)[,/& -]+cotton"),
    ("cotton", r"cotton|twill|chino|moleskin|pique"),
    ("polyester", r"poly|microfiber|acrylic|spandex|elastane|synthetic|rayon|viscose|modal|tencel|lyocell|bamboo|acetate|sequin|sheer|stretch"),
]
VOCAB = [name for name, _ in RULES] + ["other", "unknown"]
COMPILED = [(name, re.compile(pattern)) for name, pattern in RULES]


def normalize(raw: str | None) -> str:
    # primary material = the first part of "a/b", "a and b", "a, b"
    text = (raw or "").lower().replace("_", " ").strip()
    if text in ("", "unknown", "fabric", "textile", "woven", "man-made"):
        return "unknown"
    # "a/b blend" names one fabric, so don't split it
    first = text if "blend" in text else re.split(r"\s*(?:/|,|&|\+|\band\b|\bwith\b)\s*", text)[0] or text
    for part in (first, text):
        for name, rx in COMPILED:
            if rx.search(part):
                return name
    return "other"


assert normalize("faux_leather") == "faux_leather"
assert normalize("mesh/leather") == "mesh"
assert normalize("denim and faux leather") == "denim"
assert normalize("Patent Leather") == "patent_leather"
assert normalize("polyester/cotton blend") == "cotton_blend"
assert normalize("suede-ish fabric outer with sherpa fleece lining") == "faux_suede"
assert normalize("lace") == "lace"
assert normalize(None) == "unknown"

if __name__ == "__main__":
    tags = [r["tags"] for r in map(json.loads, open(sys.argv[1])) if r["tags"]]
    out = Counter(normalize(t.get("material")) for t in tags)
    print(f"tagged {len(tags)}  classes {len(out)}")
    for name in VOCAB:
        print(f"{out[name]:6}  {name}")
    other = Counter((t.get("material") or "").lower() for t in tags if normalize(t.get("material")) == "other")
    print("\nother:", other.most_common())
