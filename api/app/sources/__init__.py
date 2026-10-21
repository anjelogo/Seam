import re
import zlib
from typing import Callable, Optional

from seam_shared.models import Slot, Source

SLOT_WORDS: dict[Slot, tuple[str, ...]] = {
    Slot.top: ("tee", "shirt", "sweater", "hoodie", "longsleeve"),
    Slot.bottom: ("pants", "jeans", "shorts", "skirt", "trousers"),
    Slot.outer: ("jacket", "coat", "fleece", "windbreaker", "cardigan", "overshirt"),
    Slot.shoes: ("sneakers", "boots", "loafers", "sandals"),
    Slot.onepiece: ("dress", "jumpsuit"),
    Slot.accessory: ("hat", "bag"),
}


def slot_term(slot: Slot, query: str, page: int) -> str:
    words = SLOT_WORDS[slot]
    if set(re.findall(r"[a-z0-9]+", query.lower())) & set(words):
        return ""
    # same query/page always gets the same word
    return words[zlib.crc32(f"{query}:{page}".encode()) % len(words)]


def search_text(query: str, slot: Optional[Slot], page: int) -> str:
    if slot is None:
        return query
    term = slot_term(slot, query, page)
    return f"{query} {term}" if term else query


from app.sources import depop, ebay, grailed, poshmark  # noqa: E402

ADAPTERS: dict[Source, Callable] = {
    Source.ebay: ebay.search,
    Source.depop: depop.search,
    Source.poshmark: poshmark.search,
    Source.grailed: grailed.search,
}
