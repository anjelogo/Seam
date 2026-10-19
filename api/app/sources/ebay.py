import os
import time
from decimal import Decimal
from typing import Optional

from seam_shared.models import Condition, ImageRef, Listing, Money, Slot, Source

from app.sources import SLOT_WORD
from app.sources.fetch import api_aclient

CLOTHING_CATEGORY = "11450"
_token: tuple[str, float] = ("", 0.0)


async def _auth() -> str:
    global _token
    if time.time() < _token[1]:
        return _token[0]
    app_id, cert_id = os.getenv("EBAY_APP_ID"), os.getenv("EBAY_CERT_ID")
    if not app_id or not cert_id:
        raise RuntimeError("EBAY_APP_ID and EBAY_CERT_ID must be set")
    r = await api_aclient.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        auth=(app_id, cert_id),
        data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
    )
    r.raise_for_status()
    body = r.json()
    _token = (body["access_token"], time.time() + body["expires_in"] - 60)
    return _token[0]


async def search(query: str, slot: Optional[Slot], limit: int, page: int = 0) -> list[Listing]:
    r = await api_aclient.get(
        "https://api.ebay.com/buy/browse/v1/item_summary/search",
        headers={"Authorization": f"Bearer {await _auth()}", "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"},
        params={
            "q": f"{query} {SLOT_WORD[slot]}" if slot else query,
            "category_ids": CLOTHING_CATEGORY,
            "filter": "conditions:{USED},buyingOptions:{FIXED_PRICE}",
            "limit": limit,
            "offset": page * limit,
        },
    )
    r.raise_for_status()
    return [_listing(s) for s in r.json().get("itemSummaries", [])]


def _listing(s: dict) -> Listing:
    ship = next((o["shippingCost"] for o in s.get("shippingOptions", []) if "shippingCost" in o), None)
    return Listing(
        source=Source.ebay,
        source_id=s.get("legacyItemId") or s["itemId"].split("|")[1],
        url=s["itemWebUrl"],
        title=s["title"],
        price=Money(cents=int(Decimal(s["price"]["value"]) * 100), currency=s["price"]["currency"]),
        shipping=Money(cents=int(Decimal(ship["value"]) * 100)) if ship else None,
        condition=Condition.unknown,
        images=[ImageRef(url=i["imageUrl"]) for i in [s["image"], *s.get("additionalImages", [])] if i],
        seller=(s.get("seller") or {}).get("username"),
    )
