import asyncio
import logging
import os
import time

import httpx

log = logging.getLogger("seam.fetch")

COOLDOWN_S = 600
IP_TIMEOUT_S = 60
_lock = asyncio.Lock()
_last = 0.0


def _client(base: str) -> httpx.AsyncClient:
    auth = (os.getenv("GLUETUN_CONTROL_AUTH") or "").strip()
    if ":" in auth:
        user, pw = auth.split(":", 1)
        return httpx.AsyncClient(base_url=base, auth=(user, pw), timeout=15)
    return httpx.AsyncClient(base_url=base, headers={"X-API-Key": auth} if auth else None, timeout=15)


async def _ip(c: httpx.AsyncClient) -> str:
    try:
        r = await c.get("/v1/publicip/ip")
        return (r.json().get("public_ip") or "") if r.is_success else ""
    except (httpx.HTTPError, ValueError):
        return ""


async def rotate() -> bool:
    global _last
    base = (os.getenv("GLUETUN_CONTROL_URL") or "").strip().rstrip("/")
    if (os.getenv("GLUETUN_ROTATE") or "").strip().lower() != "true" or not base:
        log.warning("vpn rotation skipped: GLUETUN_ROTATE off or GLUETUN_CONTROL_URL unset")
        return False
    async with _lock:
        if time.monotonic() - _last < COOLDOWN_S and _last:
            log.warning("vpn rotation skipped: cooldown")
            return False
        _last = time.monotonic()
        try:
            async with _client(base) as c:
                path = "/v1/vpn/status"
                if (await c.get(path)).status_code == 404:
                    path = "/v1/openvpn/status"
                before = await _ip(c)
                (await c.put(path, json={"status": "stopped"})).raise_for_status()
                (await c.put(path, json={"status": "running"})).raise_for_status()
                deadline = time.monotonic() + IP_TIMEOUT_S
                while time.monotonic() < deadline:
                    await asyncio.sleep(3)
                    ip = await _ip(c)
                    if ip and ip != before:
                        log.info("vpn rotated")
                        return True
        except httpx.HTTPError as e:
            log.warning("vpn rotation failed: %s", type(e).__name__)
            return False
        log.warning("vpn rotation: public ip unchanged after %ds", IP_TIMEOUT_S)
        return False
