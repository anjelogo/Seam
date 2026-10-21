import argparse
import json
import sys
from pathlib import Path

DRAPE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DRAPE))


def main() -> None:
    ap = argparse.ArgumentParser(description="list the GLBs the viewer can show for one inputs/out pair")
    ap.add_argument("--inputs", type=Path, default=DRAPE / "runs/inputs")
    ap.add_argument("--out", type=Path, default=DRAPE / "runs/out")
    a = ap.parse_args()
    out = a.out.resolve()
    url = f"/gen3d/drape/{out.relative_to(DRAPE)}"

    def first(pattern: str) -> str | None:
        hits = sorted(out.glob(pattern))
        return f"{url}/{hits[0].relative_to(out)}" if hits else None

    items = []
    for it in json.loads((a.inputs / "manifest.json").read_text())["items"]:
        safe = it["safe"]
        sizes = {s: first(f"{safe}/glb/{safe}_size_{s}.glb") for s in ("XS", "M", "XL")}
        items.append({
            "safe": safe,
            "role": it.get("role"),
            "title": it.get("title", safe),
            "template": first(f"{safe}/glb/{safe}_template.glb"),
            "draped": first(f"{safe}/glb/{safe}_draped.glb"),
            "draped_legacy": first(f"{safe}/glb/{safe}_draped_legacy.glb"),
            "bound": first(f"{safe}/glb/{safe}_bound.glb"),
            "bound_legacy": first(f"{safe}/glb/{safe}_bound_legacy.glb"),
            "sizes": {k: v for k, v in sizes.items() if v},
        })
    path = out / "viewer_manifest.json"
    path.write_text(json.dumps({"items": items}, indent=2))
    print(f"{path}:")
    for i in items:
        have = [k for k in ("template", "draped", "draped_legacy", "bound", "bound_legacy") if i[k]]
        print(f"  {i['safe']}: {', '.join(have + [f'size_{s}' for s in i['sizes']]) or 'nothing yet'}")


if __name__ == "__main__":
    main()
