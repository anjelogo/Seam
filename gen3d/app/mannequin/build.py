from pathlib import Path

from seam_shared.models import TEMPLATE_FOR_CATEGORY, BodyBase

from app.mannequin.anchors import write_anchors
from app.mannequin.export import export_avatar
from app.mannequin.templates import export_template
from app.settings import ASSETS_DIR


def build(assets: Path = ASSETS_DIR) -> list[Path]:
    (assets / "templates").mkdir(parents=True, exist_ok=True)
    templates = sorted({t for t in TEMPLATE_FOR_CATEGORY.values() if t})
    out = []
    for base in (b.value for b in BodyBase):
        out.append(export_avatar(base, assets / f"avatar_{base}.glb"))
        out += [export_template(t, base, assets / "templates" / f"{t}_{base}.glb") for t in templates]
    out.append(write_anchors(assets / "anchors.json"))
    return out


if __name__ == "__main__":
    for path in build():
        print(f"{path.stat().st_size / 1e6:6.2f} MB  {path}")
