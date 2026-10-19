import logging
import os
from dataclasses import dataclass
from typing import Optional

import httpx

log = logging.getLogger("seam.fetch")


@dataclass
class Clearance:
    cookies: dict[str, str]
    user_agent: str


async def solve(url: str, proxy: str = "") -> Optional[Clearance]:
    endpoint = (os.getenv("FLARESOLVERR_URL") or "").strip()
    if not endpoint:
        return None
    body = {"cmd": "request.get", "url": url, "maxTimeout": 60000}
    if proxy:
        body["proxy"] = {"url": proxy}
    try:
        async with httpx.AsyncClient(timeout=75) as c:
            r = await c.post(endpoint, json=body)
            r.raise_for_status()
            data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("flaresolverr request failed: %s", type(e).__name__)
        return None
    sol = data.get("solution") or {}
    if data.get("status") != "ok" or not sol.get("userAgent"):
        log.warning("flaresolverr could not solve %s: %s", url, data.get("message"))
        return None
    return Clearance({c["name"]: c["value"] for c in sol.get("cookies") or []}, sol["userAgent"])
