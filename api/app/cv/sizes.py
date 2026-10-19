import re
from typing import Optional

from seam_shared.models import Slot

LETTERS = ["XS", "S", "M", "L", "XL", "XXL"]
WAIST_MIN, WAIST_MAX = 26, 40
LETTER_WAIST = {"XS": 26, "S": 28, "M": 30, "L": 32, "XL": 34, "XXL": 36}
WORDS = {"XSMALL": "XS", "EXTRASMALL": "XS", "SMALL": "S", "MEDIUM": "M", "LARGE": "L", "XLARGE": "XL", "EXTRALARGE": "XL"}
UPPER = (Slot.top, Slot.outer, Slot.onepiece)


def _parse(text: str) -> Optional[str | float]:
    """'WXL' -> 'XL', '2XL' -> 'XXL', 'US 9.5M' -> 9.5, '11J' -> 11.0, else None."""
    t = re.sub(r"[^A-Z0-9.]", "", text.upper())
    t = WORDS.get(t, re.sub(r"^(SIZE|US|EU|W)", "", t))
    if m := re.fullmatch(r"(\d)?(X*)([SML])", t):
        xs = int(m[1]) if m[1] else len(m[2])
        idx = {"S": max(0, 1 - xs), "M": 2, "L": min(5, 3 + xs)}[m[3]]
        return LETTERS[idx] if m[3] != "M" or not xs else None
    if m := re.match(r"(\d+(?:\.\d+)?)", t):
        return float(m[1])
    return None


def ladder(slot: Slot, *texts: Optional[str]) -> Optional[str]:
    """One size scale per slot: tops/outer/onepiece XS..XXL, bottoms W26..W40, shoes US<n>. First parseable text wins."""
    for text in filter(None, texts):
        v = _parse(text)
        if v is None:
            continue
        if slot in UPPER:
            if isinstance(v, str):
                return v
            # 26+ reads as a waist, smaller as a US women's dress size (0-2 XS, 4-6 S, 8-10 M...)
            return min(LETTER_WAIST, key=lambda k: abs(LETTER_WAIST[k] - v)) if v >= 26 else LETTERS[min(5, int(v // 4))]
        if slot == Slot.bottom:
            waist = LETTER_WAIST[v] if isinstance(v, str) else v if v >= 23 else round(25 + v / 2)
            return f"W{min(max(round(waist), WAIST_MIN), WAIST_MAX)}"
        if slot == Slot.shoes and isinstance(v, float):
            return f"US{v:g}"
    return None
