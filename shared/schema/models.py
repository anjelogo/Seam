"""
Shared contract — DubHacks 2026 (thrift aggregator + 3D try-on).

SOURCE OF TRUTH. `shared/schema/types.ts` mirrors this file by hand.
Change both in the same commit, and tell the other person.

Ownership:
  Caden  -> Listing, ItemTags, Item (ingest + CV), StyleQuery, Outfit (LLM)
  Anjelo -> Asset3D, GenJob (2D->3D), BodyProfile (avatar), UI
  Both   -> enums, ImageRef, Money, API envelopes

Conventions:
  - Money is integer cents. Never floats.
  - IDs are strings. ListingOffer.id = f"{source}:{source_id}" (stable across re-scrapes); Garment.id = g_<ulid>, also the compat Item.id.
  - Timestamps are UTC ISO-8601.
  - Every enum has an `other`/`unknown` escape hatch so bad data never crashes ingest.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

def _now() -> datetime:
    return datetime.now(timezone.utc)

# ───────────────────────── enums ─────────────────────────

class Source(str, Enum):
    ebay = "ebay"
    depop = "depop"
    poshmark = "poshmark"
    grailed = "grailed"
    mercari = "mercari"
    other = "other"

class Slot(str, Enum):
    """Where an item goes on the body. One item per slot per outfit."""
    top = "top"
    bottom = "bottom"
    outer = "outer"        # layered over top
    onepiece = "onepiece"  # dress/jumpsuit: fills top+bottom
    shoes = "shoes"
    accessory = "accessory"

class Category(str, Enum):
    """Fine-grained garment type. Drives TEMPLATE_FOR_CATEGORY on the 3D side."""
    # tops
    tee = "tee"
    longsleeve = "longsleeve"
    tank = "tank"
    button_up = "button_up"
    polo = "polo"
    sweater = "sweater"
    hoodie = "hoodie"
    sweatshirt = "sweatshirt"
    # outer
    jacket = "jacket"
    denim_jacket = "denim_jacket"
    leather_jacket = "leather_jacket"
    coat = "coat"
    vest = "vest"
    # bottoms
    jeans = "jeans"
    pants = "pants"
    cargo = "cargo"
    shorts = "shorts"
    skirt = "skirt"
    # onepiece
    dress = "dress"
    jumpsuit = "jumpsuit"
    # shoes / accessories
    sneakers = "sneakers"
    boots = "boots"
    shoes_other = "shoes_other"
    hat = "hat"
    bag = "bag"
    accessory_other = "accessory_other"
    unknown = "unknown"

class Condition(str, Enum):
    new_with_tags = "new_with_tags"
    like_new = "like_new"
    good = "good"
    fair = "fair"
    unknown = "unknown"

class Fit(str, Enum):
    oversized = "oversized"
    relaxed = "relaxed"
    regular = "regular"
    slim = "slim"
    cropped = "cropped"
    unknown = "unknown"

class ImageView(str, Enum):
    """What kind of photo this is. 3D quality depends heavily on this."""
    flat_lay = "flat_lay"    # best for 3D
    hanger = "hanger"        # good
    mannequin = "mannequin"  # good
    on_model = "on_model"    # needs segmentation, body occludes garment
    detail = "detail"        # tag/close-up, useless for 3D
    unknown = "unknown"

class AssetTier(str, Enum):
    template_textured = "template_textured"  # Floor: template mesh + TRELLIS.2 texturing
    generated = "generated"                  # Target: TRELLIS.2 image->3D, fitted
    voxel = "voxel"                          # Stylized fallback

class AssetStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"

class BodyBase(str, Enum):
    masc = "masc"
    fem = "fem"

# ───────────────────────── primitives ─────────────────────────

class Money(BaseModel):
    cents: int = Field(ge=0)
    currency: str = "USD"

class ImageRef(BaseModel):
    url: str                          # remote URL or /static/... path
    local_path: Optional[str] = None  # on-disk copy (server only)
    width: Optional[int] = None
    height: Optional[int] = None
    view: ImageView = ImageView.unknown

class Color(BaseModel):
    name: str            # human name: "washed black"
    hex: str             # "#2b2b2b"
    ratio: float = Field(ge=0, le=1, default=1.0)  # share of garment area

# ───────────────────────── Caden: ingest ─────────────────────────

class Listing(BaseModel):
    """Raw-ish normalized listing straight from a source. No CV yet."""
    source: Source
    source_id: str
    url: str
    title: str
    description: Optional[str] = None
    price: Money
    shipping: Optional[Money] = None
    condition: Condition = Condition.unknown
    brand: Optional[str] = None
    size_raw: Optional[str] = None    # exactly as listed: "M", "32x30", "US 10"
    images: list[ImageRef] = []
    seller: Optional[str] = None
    scraped_at: datetime = Field(default_factory=_now)

# ───────────────────────── Caden: CV / tagging ─────────────────────────

class ItemTags(BaseModel):
    """Output of the vision/tagging pass on a Listing."""
    slot: Slot
    category: Category
    colors: list[Color] = []
    pattern: Optional[str] = None     # "solid", "plaid", "graphic", "striped"
    material: Optional[str] = None    # one of MATERIALS
    fit: Fit = Fit.unknown
    style_tags: list[str] = []        # lowercase: ["grunge", "y2k", "emo"]
    era: Optional[str] = None         # "2000s", "90s"
    size_normalized: Optional[str] = None  # "M", "W32", "US10"
    confidence: float = Field(ge=0, le=1, default=0.5)
    est_retail: Optional[Money] = None       # v2: estimated new-retail price, feeds savings_vs_retail
    tagger: Optional[str] = None             # v2: model that produced these tags, e.g. "perceptron-mk1.5"

    # ---- the handoff to Anjelo's 3D pipeline ----
    clean_image: Optional[ImageRef] = None   # bg removed, garment only, RGBA PNG
    best_view_index: int = 0                 # index into Listing.images used for clean_image
    garment_box: Optional[tuple[float, float, float, float]] = None  # v2: [x0,y0,x1,y1] 0..1 in images[best_view_index]
    usable_for_3d: bool = False              # Caden's call: single garment, front view, not cropped
    unusable_reason: Optional[str] = None    # "on_model_occluded", "multiple_items", "detail_shot"

class Item(BaseModel):
    """The unit everything else references. Listing + tags (+ 3D once ready)."""
    id: str                                  # f"{source}:{source_id}"
    listing: Listing
    tags: Optional[ItemTags] = None          # None until tagged
    asset: Optional["Asset3D"] = None        # None until 3D is ready (Anjelo fills)

    @classmethod
    def make_id(cls, source: Source, source_id: str) -> str:
        return f"{source.value}:{source_id}"

# ───────────────────────── Caden: outfit LLM ─────────────────────────

class SizeProfile(BaseModel):
    top: Optional[str] = None      # "M"
    bottom: Optional[str] = None   # "W32"
    shoes: Optional[str] = None    # "US10"

class StyleQuery(BaseModel):
    """What the UI sends when the user hits 'Find outfits'."""
    prompt: str                                  # "grunge emo 2000s"
    budget: Optional[Money] = None               # total outfit cap
    sizes: SizeProfile = SizeProfile()
    slots: list[Slot] = [Slot.top, Slot.bottom, Slot.outer, Slot.shoes]
    sources: list[Source] = []                   # empty = all
    num_outfits: int = Field(default=3, ge=1, le=6)
    require_3d_ready: bool = False               # demo mode: only items with assets
    body: Optional["BodyProfile"] = None         # v2: avatar shape, lets the LLM reason about fit
    previous_outfit_ids: list[str] = []          # v2: refine round: outfits being replaced
    feedback: Optional[str] = None               # v2: refine round: "cheaper, darker jacket"

class OutfitPiece(BaseModel):
    item_id: str
    reason: str                       # one line from the LLM: why this piece fits the vibe
    alternates: list[str] = []        # other item_ids valid for this slot (powers the swap UI)

class Outfit(BaseModel):
    id: str
    name: str                         # "Basement Show Regular"
    vibe_summary: str                 # 1–2 sentences
    pieces: dict[Slot, OutfitPiece]   # keyed by slot
    total: Money                      # sum of item prices (+ shipping if known)
    savings_vs_retail: Optional[Money] = None  # optional Visa-angle stat
    within_budget: bool = True

# ───────────────────────── Anjelo: 3D ─────────────────────────

class Transform(BaseModel):
    """Placement of a garment GLB on the avatar, avatar-local space, meters."""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)  # euler XYZ, radians
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

class Asset3D(BaseModel):
    item_id: str
    status: AssetStatus = AssetStatus.queued
    tier: AssetTier
    template_id: Optional[str] = None     # set when tier == template_textured, e.g. "tee_v1"
    glb_url: Optional[str] = None         # /static/glb/<item_id>.glb
    voxel_glb_url: Optional[str] = None   # optional stylized variant
    thumbnail_url: Optional[str] = None   # turntable still for cards
    fit: Transform = Transform()          # only meaningful for tier == generated
    follows_body_morphs: bool = False     # True for templates w/ matching shape keys
    gen_seconds: Optional[float] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)

class GenJob(BaseModel):
    """Request into the gen3d service."""
    item_id: str
    image_url: str                        # usually ItemTags.clean_image.url
    category: Category
    tier: AssetTier = AssetTier.template_textured
    resolution: int = 512                 # 512 | 1024; 512 for live, 1024 for pre-bake

# Category -> template mesh. None = no template yet (falls back to `generated`).
TEMPLATE_FOR_CATEGORY: dict[Category, Optional[str]] = {
    Category.tee: "tee_v1",
    Category.tank: "tee_v1",
    Category.polo: "tee_v1",
    Category.longsleeve: "longsleeve_v1",
    Category.button_up: "longsleeve_v1",
    Category.sweater: "longsleeve_v1",
    Category.sweatshirt: "longsleeve_v1",
    Category.hoodie: "hoodie_v1",
    Category.jacket: "jacket_v1",
    Category.denim_jacket: "jacket_v1",
    Category.leather_jacket: "jacket_v1",
    Category.coat: "coat_v1",
    Category.vest: None,
    Category.jeans: "pants_v1",
    Category.pants: "pants_v1",
    Category.cargo: "pants_v1",
    Category.shorts: "shorts_v1",
    Category.skirt: "skirt_v1",
    Category.dress: "dress_v1",
    Category.jumpsuit: None,
    Category.sneakers: "shoe_v1",
    Category.boots: "boot_v1",
    Category.shoes_other: "shoe_v1",
    Category.hat: None,
    Category.bag: None,
    Category.accessory_other: None,
    Category.unknown: None,
}

# ───────────────────────── Anjelo: avatar ─────────────────────────

class BodyProfile(BaseModel):
    """
    Slider state. All sliders are 0..1 and map 1:1 to GLB morph targets
    of the same name (minus the `_`), so the frontend can loop over them.
    0.5 = base mesh.
    """
    base: BodyBase = BodyBase.masc
    height: float = Field(default=0.5, ge=0, le=1)
    weight: float = Field(default=0.5, ge=0, le=1)
    muscle: float = Field(default=0.5, ge=0, le=1)
    shoulders: float = Field(default=0.5, ge=0, le=1)
    chest: float = Field(default=0.5, ge=0, le=1)
    waist: float = Field(default=0.5, ge=0, le=1)
    hips: float = Field(default=0.5, ge=0, le=1)
    leg_length: float = Field(default=0.5, ge=0, le=1)
    skin_tone: str = "#c68e6a"

# ───────────────────────── API envelopes ─────────────────────────

class OutfitResponse(BaseModel):
    """POST /outfits -> this. Items are de-duplicated into a lookup map."""
    query: StyleQuery
    outfits: list[Outfit]
    items: dict[str, Item]            # item_id -> Item (includes alternates)
    took_ms: int = 0

class ItemsResponse(BaseModel):
    """GET /items?slot=&category=&q= -> this. For browse/swap."""
    items: list[Item]
    total: int

class ApiError(BaseModel):
    error: str
    detail: Optional[str] = None

# ───────────────────────── v3: garments, listings, photos ─────────────────────────
# A Garment is one physical object; each ListingOffer is one store selling it.
# Garment-level facts: tags, best photo, cutout, 3D asset. Listing-level facts: price, shipping, condition, seller, status.

class PhotoState(str, Enum):
    spread = "spread"
    folded = "folded"
    bunched = "bunched"
    unknown = "unknown"

class Wrinkle(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    unknown = "unknown"

class ListingStatus(str, Enum):
    active = "active"
    sold = "sold"
    gone = "gone"

class Photo(BaseModel):
    id: int
    listing_id: str
    idx: int
    url: str
    width: Optional[int] = None
    height: Optional[int] = None
    view: ImageView = ImageView.unknown
    rotation: Literal[0, 90, 180, 270] = 0    # clockwise degrees to make the garment upright, applied before cutout
    state: PhotoState = PhotoState.unknown
    wrinkle: Wrinkle = Wrinkle.unknown

class PatternKind(str, Enum):
    solid = "solid"
    stripes = "stripes"
    pinstripes = "pinstripes"
    plaid = "plaid"
    check = "check"
    houndstooth = "houndstooth"
    camo = "camo"
    floral = "floral"
    graphic = "graphic"
    other = "other"

class StripeSet(BaseModel):
    """A repeating pattern relative to the fabric grain (grain = garment up/down)."""
    direction: Literal["grain", "cross", "bias"] = "grain"   # grain = vertical on a leg or torso
    period_cm: float = Field(gt=0, le=60)
    line_width_cm: float = Field(gt=0, le=30)
    colors: list[str] = Field(min_length=1)                   # hex; cycles across the repeat
    offset_cm: float = 0.0

class Trim(BaseModel):
    """A placed linear feature that follows a seam or edge, e.g. track-pant side stripes."""
    kind: Literal["side_stripe", "piping", "waistband", "cuff", "hem_band", "placket", "yoke", "other"]
    placement: Literal["outseam", "inseam", "center_front", "center_back", "shoulder", "sleeve_outer", "hem", "waist", "cuff", "other"]
    colors: list[str] = Field(min_length=1)                   # one per band, outermost first
    widths_cm: list[float] = Field(min_length=1)               # same length as colors
    gap_cm: float = 0.0                                        # between bands
    extent: Literal["full", "upper", "lower"] = "full"

class Placement(BaseModel):
    """A one-off print/logo/patch cut from the cutout and placed on a panel."""
    kind: Literal["logo", "print", "patch", "pocket", "text", "other"]
    box: tuple[float, float, float, float]                    # [x0,y0,x1,y1] 0..1 in clean_image
    panel: Literal["front", "back", "left_front", "right_front", "left_back", "right_back", "left_sleeve", "right_sleeve", "hood", "other"] = "front"

class PatternSpec(BaseModel):
    kind: PatternKind = PatternKind.solid
    base_color: Optional[str] = None                           # hex of the ground fabric
    repeats: list[StripeSet] = []
    trims: list[Trim] = []
    placements: list[Placement] = []
    confidence: float = Field(ge=0, le=1, default=0.5)

class ListingOffer(BaseModel):
    id: str                                                    # f"{source}:{source_id}"
    source: Source
    url: str
    title: str
    description: Optional[str] = None
    price: Money
    shipping: Optional[Money] = None
    seller: Optional[str] = None
    size_raw: Optional[str] = None
    brand_raw: Optional[str] = None
    stated_condition: Condition = Condition.unknown            # what the seller claims
    assessed_condition: Condition = Condition.unknown          # what our model sees in this listing's photos (shown in UI)
    status: ListingStatus = ListingStatus.active
    photos: list[Photo] = []
    first_seen: datetime = Field(default_factory=_now)
    last_seen: datetime = Field(default_factory=_now)

    def total_cents(self) -> int:
        return self.price.cents + (self.shipping.cents if self.shipping else 0)

class Garment(BaseModel):
    id: str                                                    # g_<ulid>
    tags: Optional[ItemTags] = None                            # garment-level, from all listings' photos
    pattern_spec: Optional[PatternSpec] = None                 # drives texturing
    best_photo: Optional[Photo] = None
    listings: list[ListingOffer] = Field(min_length=1)         # active first, then cheapest total
    best_listing_id: str                                       # cheapest active price + shipping: the one price the card shows
    asset: Optional[Asset3D] = None

    def best_listing(self) -> ListingOffer:
        return next(l for l in self.listings if l.id == self.best_listing_id)

class GarmentsResponse(BaseModel):
    garments: list[Garment]
    total: int

class OutfitResponseV3(BaseModel):
    query: StyleQuery
    outfits: list[Outfit]                                      # OutfitPiece.item_id holds a garment id in v3
    garments: dict[str, Garment]
    took_ms: int = 0

# ───────────────────────── material vocabulary ─────────────────────────
# ItemTags.material stays Optional[str], but the tagger may only write one of these.
MATERIALS = (
    "cotton_jersey", "cotton_twill", "denim", "corduroy", "canvas", "fleece", "knit", "wool", "flannel",
    "linen", "silk_satin", "nylon", "polyester", "leather", "faux_leather", "suede", "rubber", "mesh", "other",
)
_MATERIAL_ALIASES = {
    "pleather": "faux_leather", "vegan leather": "faux_leather", "pu": "faux_leather", "faux leather": "faux_leather",
    "jersey": "cotton_jersey", "cotton": "cotton_jersey", "twill": "cotton_twill", "chino": "cotton_twill",
    "sweater": "knit", "cashmere": "knit", "acrylic": "knit", "rib": "knit", "sherpa": "fleece",
    "satin": "silk_satin", "silk": "silk_satin", "nubuck": "suede", "leather": "leather",
}

def normalize_material(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw.strip().lower().replace("-", " ")
    if s.replace(" ", "_") in MATERIALS:
        return s.replace(" ", "_")
    for alias, m in sorted(_MATERIAL_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if alias in s:
            return m
    return "other"

Item.model_rebuild()
StyleQuery.model_rebuild()
OutfitResponse.model_rebuild()
Garment.model_rebuild()
OutfitResponseV3.model_rebuild()
