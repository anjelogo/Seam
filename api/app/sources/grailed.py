import time
from typing import Optional

from seam_shared.models import Condition, ImageRef, Listing, Money, Slot, Source

from app.sources import client

# public search-only key served to every visitor in grailed.com's PUBLIC_CONFIG
ALGOLIA = "https://MNRWEFSS2Q-dsn.algolia.net/1/indexes/Listing_by_heat_production/query"
ALGOLIA_HEADERS = {"X-Algolia-Application-Id": "MNRWEFSS2Q", "X-Algolia-API-Key": "c89dbaddf15fe70e1941a109bf7c2a3d"}

CATEGORIES = {
    Slot.top: ["tops", "womens_tops"],
    Slot.bottom: ["bottoms", "womens_bottoms"],
    Slot.outer: ["outerwear", "womens_outerwear"],
    Slot.onepiece: ["womens_dresses"],
    Slot.shoes: ["footwear", "womens_footwear"],
    Slot.accessory: ["accessories", "womens_accessories"],
}

CONDITION = {
    "is_new": Condition.new_with_tags,
    "is_gently_used": Condition.like_new,
    "is_used": Condition.good,
    "is_worn": Condition.fair,
}


def search(query: str, slot: Optional[Slot], limit: int) -> list[Listing]:
    body = {"query": query, "hitsPerPage": limit}
    if slot:
        body["facetFilters"] = [[f"category:{c}" for c in CATEGORIES[slot]]]
    r = client.post(ALGOLIA, headers=ALGOLIA_HEADERS, json=body)
    r.raise_for_status()
    return [_listing(h) for h in r.json()["hits"] if not h.get("sold") and not h.get("deleted")]


def _listing(hit: dict) -> Listing:
    # search hits carry only the cover photo; the detail endpoint has all photos and the description
    time.sleep(0.5)
    r = client.get(f"https://www.grailed.com/api/listings/{hit['id']}")
    r.raise_for_status()
    detail = r.json()["data"]
    us = (hit.get("shipping") or {}).get("us") or {}
    return Listing(
        source=Source.grailed,
        source_id=str(hit["id"]),
        url=f"https://www.grailed.com/listings/{hit['id']}",
        title=hit["title"],
        description=detail.get("description"),
        price=Money(cents=int(hit["price_i"]) * 100),
        shipping=Money(cents=int(us["amount"]) * 100) if us.get("enabled") else None,
        condition=CONDITION.get(hit.get("condition"), Condition.unknown),
        brand=hit.get("designer_names"),
        size_raw=hit.get("size"),
        images=[ImageRef(url=p["url"]) for p in detail.get("photos") or [hit["cover_photo"]]],
        seller=(hit.get("user") or {}).get("username"),
    )
