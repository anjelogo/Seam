import io
import threading
from typing import Optional

from perceptron import Client, image
from PIL import Image, ImageChops, ImageDraw, ImageFilter
from rembg import new_session, remove
from seam_shared.models import Category, ImageRef, ImageView

from app import db

SIZE = 1024
MAX_POINTS = 12
# props behind or around the garment can be segmented away; anything else (bag, strap, belt, jewelry, layered clothing) covers fabric
REMOVABLE = ("hanger", "mannequin", "body", "skin", "hair", "neck", "head", "stand", "background", "object")
_sessions = {}
_lock = threading.Lock()
_infer_lock = threading.Lock()


def _session(name: str):
    with _lock:
        if name not in _sessions:
            _sessions[name] = new_session(name)
        return _sessions[name]


def _remove(*args, **kwargs):
    # one inference at a time: parallel SAM runs exceed 16 GB and get the process killed
    with _infer_lock:
        return remove(*args, **kwargs)


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _extras(img: Image.Image, garment: str) -> list[tuple[float, float, str]]:
    """Perceptron points (x, y, name) on visible parts of anything that is not the garment (hanger, mannequin, bag...)."""
    with Client() as c:
        out = c.chat.completions.create(
            model="perceptron-mk1.5",
            temperature=0,
            messages=[{"role": "user", "content": [image(_jpeg(img)),
                f"Point to one clearly visible spot on each object that is NOT the {garment}: hanger, mannequin, body, skin, hair, bag, bag strap, "
                f"belt, jewelry, other clothing. Label each point with what it is. Never point on the {garment} itself. "
                f"If there is nothing but the {garment}, give no points."]}],
        )
    # the model sometimes degenerates into hundreds of points; a handful is plenty for SAM
    pts = out.annotations(expects="point").points[:MAX_POINTS]
    return [(p.x * img.width / 1000, p.y * img.height / 1000, p.mention or "object") for p in pts]


def _garment_points(alpha: Image.Image, extras: list[tuple[float, float, str]]) -> list[tuple[float, float]]:
    """A 5x5 grid over the foreground, skipping spots near the extras so SAM sees the whole garment."""
    core = alpha.filter(ImageFilter.MinFilter(15))
    x0, y0, x1, y1 = core.getbbox() or (0, 0, *alpha.size)
    near = 0.08 * max(alpha.size)
    grid = [(x0 + (x1 - x0) * (i + 0.5) / 5, y0 + (y1 - y0) * (j + 0.5) / 5) for i in range(5) for j in range(5)]
    return [(x, y) for x, y in grid if core.getpixel((int(x), int(y))) > 200 and all(abs(x - ex) + abs(y - ey) > near for ex, ey, _ in extras)]


def _fill_holes(mask: Image.Image) -> Image.Image:
    padded = Image.new("L", (mask.width + 2, mask.height + 2), 0)
    padded.paste(mask.point(lambda v: 255 if v > 127 else 0), (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)
    return padded.point(lambda v: 0 if v == 128 else 255).crop((1, 1, mask.width + 1, mask.height + 1))


def cutout(item_id: str, path: str, box: tuple[float, float, float, float], view: ImageView, category: Category) -> tuple[ImageRef, Optional[str]]:
    """Crop to garment_box (+5% margin), keep only the garment, square-pad to 1024 RGBA.
    Returns the cutout and an unusable_reason if anything besides the garment survived."""
    garment = category.value.replace("_", " ")
    img = Image.open(path).convert("RGB")
    w, h = img.size
    mx, my = (box[2] - box[0]) * 0.05, (box[3] - box[1]) * 0.05
    img = img.crop((int(max(box[0] - mx, 0) * w), int(max(box[1] - my, 0) * h), int(min(box[2] + mx, 1) * w), int(min(box[3] + my, 1) * h)))
    img.thumbnail((SIZE, SIZE))

    edges = _remove(img, session=_session("birefnet-general-lite")).getchannel("A")
    problem = None
    extras = _extras(img, garment)
    if extras:
        keep = _garment_points(edges, extras)
        prompt = [{"type": "point", "data": [x, y], "label": 1} for x, y in keep] + [{"type": "point", "data": [x, y], "label": 0} for x, y, _ in extras]
        region = _fill_holes(_remove(img, session=_session("sam"), sam_prompt=prompt).getchannel("A"))
        cleaned = ImageChops.multiply(edges, region.filter(ImageFilter.MaxFilter(7)))
        fg = lambda m: sum(1 for v in m.getdata() if v > 127)
        inner = cleaned.filter(ImageFilter.MinFilter(9))
        survived = {name for x, y, name in extras if inner.getpixel((int(x), int(y))) > 127}
        covering = {name for _, _, name in extras if not any(k in name.lower() for k in REMOVABLE)}
        if survived | covering:
            problem = "extra_objects: " + ", ".join(sorted(survived | covering))
        elif not keep or fg(cleaned) < 0.75 * fg(edges):
            problem = "cutout_incomplete"
        edges = cleaned
    rgba = img.convert("RGBA")
    rgba.putalpha(edges)
    rgba = rgba.crop(edges.getbbox() or (0, 0, *rgba.size))

    side = int(max(rgba.size) * 1.08)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
    square = square.resize((SIZE, SIZE), Image.LANCZOS)
    name = item_id.replace(":", "_") + ".png"
    out = db.DATA_DIR / "clean" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    square.save(out)
    ref = ImageRef(url=f"/static/clean/{name}", local_path=str(out), width=SIZE, height=SIZE, view=view)
    return ref, problem
