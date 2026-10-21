import io
import threading
from typing import NamedTuple, Optional

from perceptron import Client, image
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from rembg import new_session, remove
from seam_shared.models import Category, ImageRef, ImageView, PhotoState, Slot

from app.settings import DATA_DIR

SIZE = 1024
MAX_POINTS = 12
# props behind or around the garment can be segmented away; anything else (bag, strap, belt, jewelry, layered clothing) covers fabric
REMOVABLE = ("hanger", "mannequin", "body", "skin", "hair", "neck", "head", "stand", "background", "object")
ROTATE = {90: Image.Transpose.ROTATE_270, 180: Image.Transpose.ROTATE_180, 270: Image.Transpose.ROTATE_90}
# a spread top or bottom has concave gaps (armpits, crotch); a folded one fills its hull. Skirts are convex spread, so they are skipped.
FOLD_SOLIDITY = {Slot.top: 0.93, Slot.outer: 0.93, Slot.bottom: 0.95}
_sessions = {}
_lock = threading.Lock()
_infer_lock = threading.Lock()


class Cut(NamedTuple):
    ref: ImageRef
    problem: Optional[str]
    boxes: list[tuple[float, float, float, float]]
    solidity: Optional[float]


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


def _hull(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Monotone chain over x-sorted points."""
    def half(seq):
        out = []
        for p in seq:
            while len(out) > 1 and (out[-1][0] - out[-2][0]) * (p[1] - out[-2][1]) <= (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0]):
                out.pop()
            out.append(p)
        return out

    return half(points)[:-1] + half(points[::-1])[:-1]


def _solidity(mask: Image.Image) -> Optional[float]:
    """Foreground area over the area of its convex hull: near 1.0 means the silhouette has no armpit or crotch gaps."""
    flat = mask.point(lambda v: 255 if v > 127 else 0).tobytes()
    area, points = 0, []
    for y in range(mask.height):
        row = flat[y * mask.width : (y + 1) * mask.width]
        left = row.find(255)
        if left < 0:
            continue
        area += row.count(255)
        right = row.rfind(255) + 1
        points += [(left, y), (left, y + 1), (right, y), (right, y + 1)]
    hull = _hull(sorted(set(points)))
    if not area or len(hull) < 3:
        return None
    full = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(hull, hull[1:] + hull[:1]))) / 2
    return area / full if full else None


def _map_boxes(boxes, size: tuple[int, int], crop: tuple[int, ...], scale: float, bbox: tuple[int, ...],
               side: int, dx: int, dy: int) -> list[tuple[float, float, float, float]]:
    """Unit boxes in the upright photo -> unit boxes in the square cutout."""
    w, h = size
    out = []
    for box in boxes:
        x0, y0, x1, y1 = (min(max(v, 0.0), 1.0) for v in box)
        xs = [(x * w - crop[0]) * scale - bbox[0] + dx for x in (x0, x1)]
        ys = [(y * h - crop[1]) * scale - bbox[1] + dy for y in (y0, y1)]
        out.append(tuple(min(max(v / side, 0.0), 1.0) for v in (xs[0], ys[0], xs[1], ys[1])))
    return out


def cutout(garment_id: str, path: str, box: tuple[float, float, float, float], view: ImageView, category: Category, slot: Slot,
           rotation: int = 0, state: PhotoState = PhotoState.unknown, boxes=()) -> Cut:
    """Rotate upright, crop to garment_box (+5% margin), keep only the garment, square-pad to 1024 RGBA.
    Returns the cutout, an unusable_reason if anything besides the garment survived or the garment looks folded,
    the given boxes mapped into the cutout and the silhouette solidity."""
    garment = category.value.replace("_", " ")
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if rotation:
        img = img.transpose(ROTATE[rotation])
    w, h = img.size
    mx, my = (box[2] - box[0]) * 0.05, (box[3] - box[1]) * 0.05
    crop = (int(max(box[0] - mx, 0) * w), int(max(box[1] - my, 0) * h), int(min(box[2] + mx, 1) * w), int(min(box[3] + my, 1) * h))
    img = img.crop(crop)
    wide = max(img.width, 1)
    img.thumbnail((SIZE, SIZE))
    scale = img.width / wide

    edges = _remove(img, session=_session("birefnet-general-lite")).getchannel("A")
    problem = None
    extras = _extras(img, garment)
    if extras:
        keep = _garment_points(edges, extras)
        prompt = [{"type": "point", "data": [x, y], "label": 1} for x, y in keep] + [{"type": "point", "data": [x, y], "label": 0} for x, y, _ in extras]
        region = _fill_holes(_remove(img, session=_session("sam"), sam_prompt=prompt).getchannel("A"))
        cleaned = ImageChops.multiply(edges, region.filter(ImageFilter.MaxFilter(7)))
        def fg(m: Image.Image) -> int:
            return sum(1 for v in m.getdata() if v > 127)

        inner = cleaned.filter(ImageFilter.MinFilter(9))
        survived = {name for x, y, name in extras if inner.getpixel((int(x), int(y))) > 127}
        covering = {name for _, _, name in extras if not any(k in name.lower() for k in REMOVABLE)}
        if survived | covering:
            problem = "extra_objects: " + ", ".join(sorted(survived | covering))
        elif not keep or fg(cleaned) < 0.75 * fg(edges):
            problem = "cutout_incomplete"
        edges = cleaned
    solidity = _solidity(edges)
    limit = FOLD_SOLIDITY.get(slot) if not (slot == Slot.bottom and category == Category.skirt) else None
    if problem is None and state == PhotoState.spread and limit and solidity and solidity > limit:
        problem = "folded"
    rgba = img.convert("RGBA")
    rgba.putalpha(edges)
    bbox = edges.getbbox() or (0, 0, *rgba.size)
    rgba = rgba.crop(bbox)

    side = int(max(rgba.size) * 1.08)
    dx, dy = (side - rgba.width) // 2, (side - rgba.height) // 2
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(rgba, (dx, dy))
    square = square.resize((SIZE, SIZE), Image.LANCZOS)
    name = f"{garment_id}.png"
    out = DATA_DIR / "clean" / name
    out.parent.mkdir(parents=True, exist_ok=True)
    square.save(out)
    ref = ImageRef(url=f"/static/clean/{name}", local_path=str(out), width=SIZE, height=SIZE, view=view)
    return Cut(ref, problem, _map_boxes(boxes, (w, h), crop, scale, bbox, side, dx, dy), solidity)
