import json
from decimal import Decimal
from typing import Optional

from seam_shared.models import Condition, ImageRef, Listing, Money, Slot, Source

from app.sources import SLOT_WORD, client

CONDITION = {
    "nwt": Condition.new_with_tags,
    "uln": Condition.like_new,
    "ug": Condition.good,
    "uf": Condition.fair,
}


def search(query: str, slot: Optional[Slot], limit: int) -> list[Listing]:
    # shortcut: first results page only (~48 listings), add max_id paging if seeding needs more
    q = f"{query} {SLOT_WORD[slot]}" if slot else query
    html = client.get("https://poshmark.com/search", params={"query": q, "type": "listings", "availability": "available"})
    html.raise_for_status()
    state = html.text[html.text.index("__INITIAL_STATE__") :]
    state, _ = json.JSONDecoder().raw_decode(state[state.index("{") :])
    return [_listing(p) for p in state["$_search"]["gridData"]["data"][:limit]]


def _listing(p: dict) -> Listing:
    return Listing(
        source=Source.poshmark,
        source_id=p["id"],
        url=f"https://poshmark.com/listing/{p['id']}",
        title=p["title"],
        description=p.get("description"),
        price=Money(cents=int(Decimal(p["price_amount"]["val"]) * 100), currency=p["price_amount"]["currency_code"]),
        condition=CONDITION.get(p.get("condition"), Condition.unknown),
        brand=p.get("brand"),
        size_raw=p.get("size"),
        images=[ImageRef(url=pic["url_large"]) for pic in [p["cover_shot"], *p.get("pictures", [])]],
        seller=p.get("creator_username"),
    )
