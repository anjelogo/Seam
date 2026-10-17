import httpx
from seam_shared.models import Slot

client = httpx.Client(
    headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Accept-Language": "en-US",
    },
    timeout=20,
    follow_redirects=True,
)

SLOT_WORD = {
    Slot.top: "top",
    Slot.bottom: "pants",
    Slot.outer: "jacket",
    Slot.onepiece: "dress",
    Slot.shoes: "shoes",
    Slot.accessory: "accessories",
}
