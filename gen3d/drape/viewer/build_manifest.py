import json
import sys
from pathlib import Path

DRAPE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DRAPE))
OUT = DRAPE / "runs/out"
URL = "/gen3d/drape/runs/out"


def url_for(path: Path | None) -> str | None:
    return f"{URL}/{path.relative_to(OUT)}" if path else None


def first(pattern: str) -> Path | None:
    hits = sorted(OUT.glob(pattern))
    return hits[0] if hits else None


def main() -> None:
    mf = json.loads((DRAPE / "runs/inputs/manifest.json").read_text())
    items = []
    for it in mf["items"]:
        safe = it["safe"]
        sizes = {s: url_for(first(f"{safe}/glb/{safe}_size_{s}.glb")) for s in ("XS", "M", "XL")}
        items.append({
            "safe": safe,
            "role": it.get("role"),
            "title": it.get("title", safe),
            "template": url_for(first(f"{safe}/glb/{safe}_template.glb")),
            "draped": url_for(first(f"{safe}/glb/{safe}_draped.glb")),
            "bound": url_for(first(f"{safe}/glb/{safe}_bound.glb")),
            "sizes": {k: v for k, v in sizes.items() if v},
        })
    out = OUT / "viewer_manifest.json"
    out.write_text(json.dumps({"items": items}, indent=2))
    print(f"{out}:")
    for i in items:
        have = [k for k in ("template", "draped", "bound") if i[k]] + [f"size_{s}" for s in i["sizes"]]
        print(f"  {i['safe']}: {', '.join(have) or 'nothing yet'}")


if __name__ == "__main__":
    main()
