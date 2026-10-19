from typing import Callable

from seam_shared.models import Slot, Source

SLOT_WORD = {
    Slot.top: "top",
    Slot.bottom: "pants",
    Slot.outer: "jacket",
    Slot.onepiece: "dress",
    Slot.shoes: "shoes",
    Slot.accessory: "accessories",
}

from app.sources import depop, ebay, grailed, poshmark  # noqa: E402

ADAPTERS: dict[Source, Callable] = {
    Source.ebay: ebay.search,
    Source.depop: depop.search,
    Source.poshmark: poshmark.search,
    Source.grailed: grailed.search,
}
