"""PatternSpec: the fabric pattern of one garment in cloth cm (v3 schema copy until garments-v3 merges)."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from drape._repo import bootstrap

bootstrap()

from seam_shared.models import Color  # noqa: E402


class PatternKind(str, Enum):
    solid = "solid"
    stripes = "stripes"
    pinstripes = "pinstripes"
    plaid = "plaid"
    graphic = "graphic"
    camo = "camo"
    floral = "floral"
    other = "other"


class StripeDirection(str, Enum):
    # the way the lines run relative to the panel grain: grain = vertical on a hanging garment
    grain = "grain"
    cross = "cross"
    bias = "bias"


class TrimKind(str, Enum):
    stripe = "stripe"
    piping = "piping"
    binding = "binding"
    cuff = "cuff"
    waistband = "waistband"
    collar = "collar"
    other = "other"


class TrimPlacement(str, Enum):
    outseam = "outseam"
    inseam = "inseam"
    center_front = "center_front"
    center_back = "center_back"
    shoulder = "shoulder"
    sleeve_outer = "sleeve_outer"
    hem = "hem"
    waist = "waist"
    cuff = "cuff"
    other = "other"


class TrimExtent(str, Enum):
    full = "full"
    upper = "upper"
    lower = "lower"


class PlacementKind(str, Enum):
    graphic = "graphic"
    logo = "logo"
    text = "text"
    patch = "patch"
    pocket = "pocket"
    other = "other"


class PlacementPanel(str, Enum):
    front = "front"
    back = "back"
    left_sleeve = "left_sleeve"
    right_sleeve = "right_sleeve"
    left_leg = "left_leg"
    right_leg = "right_leg"
    hood = "hood"
    other = "other"


class StripeSet(BaseModel):
    direction: StripeDirection
    period_cm: float = Field(gt=0)
    line_width_cm: float = Field(gt=0)
    colors: list[Color] = []
    offset_cm: float = 0.0


class Trim(BaseModel):
    kind: TrimKind
    placement: TrimPlacement
    colors: list[Color] = []
    widths_cm: list[float] = []
    # between bands, and between an edge and its first band for hem/waist/cuff trims
    gap_cm: float = Field(ge=0, default=0.0)
    extent: TrimExtent = TrimExtent.full


class Placement(BaseModel):
    kind: PlacementKind
    # x0, y0, x1, y1 as fractions of the cutout image
    box: tuple[float, float, float, float]
    panel: PlacementPanel


class PatternSpec(BaseModel):
    kind: PatternKind
    base_color: Color
    repeats: list[StripeSet] = []
    trims: list[Trim] = []
    placements: list[Placement] = []
    confidence: float = Field(ge=0, le=1, default=0.5)
