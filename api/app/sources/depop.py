import json
import re
from decimal import Decimal
from typing import Optional

from seam_shared.models import Condition, ImageRef, Listing, Money, Slot, Source

from app.sources import SLOT_WORD
from app.sources.fetch import fetch

CONDITION = {
    "brand_new": Condition.new_with_tags,
    "used_like_new": Condition.like_new,
    "used_excellent": Condition.good,
    "used_good": Condition.good,
    "used_fair": Condition.fair,
}
# the search page streams its data as Next.js flight chunks: self.__next_f.push([1,"<json string>"])
FLIGHT = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')


async def search(query: str, slot: Optional[Slot], limit: int, page: int = 0) -> list[Listing]:
    # shortcut: first 24 results only (the page ignores cursors, the paging API is gone); vary queries for more
    if page:
        return []
    q = f"{query} {SLOT_WORD[slot]}" if slot else query
    html = await fetch("https://www.depop.com/search/", source=Source.depop, params={"q": q})
    html.raise_for_status()
    flight = "".join(json.loads(s) for s in FLIGHT.findall(html.text))
    pages, _ = json.JSONDecoder().raw_decode(flight, flight.index('"pages":[{"searchId"') + len('"pages":'))
    found = [o for p in pages for o in p["data"]["objects"] if o.get("status") == "STATUS_ONSALE"]
    return [_listing(o) for o in found[:limit]]


def _listing(o: dict) -> Listing:
    pricing = o["pricing"]
    amounts = pricing[pricing["final_price_key"]]["price_breakdown"]
    currency = pricing["currency"]
    ship = amounts.get("shipping")
    description = (o.get("description") or "").strip()
    return Listing(
        source=Source.depop,
        source_id=str(o["id"]),
        url=f"https://www.depop.com/products/{o['slug']}/",
        # depop has no title field; its own product pages use the description's first line
        title=description.split("\n", 1)[0][:80] or o["slug"],
        description=description or None,
        price=Money(cents=int(Decimal(amounts["price"]["amount"]) * 100), currency=currency),
        shipping=Money(cents=int(Decimal(ship["amount"]) * 100), currency=currency) if ship else None,
        condition=CONDITION.get((o.get("attributes") or {}).get("condition"), Condition.unknown),
        brand=o.get("brand_name"),
        size_raw=", ".join(s["name"] for s in o.get("sizes") or []) or None,
        images=[ImageRef(url=p["formats"]["P0"]["url"]) for p in o.get("pictures") or []],
    )
