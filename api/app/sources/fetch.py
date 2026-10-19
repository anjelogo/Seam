import asyncio
import json as jsonlib
import logging
import os
import random
import time
import weakref
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

import httpx
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import ConnectionError as CurlConnectionError
from curl_cffi.requests.exceptions import Timeout as CurlTimeout
from seam_shared.models import Source

from app.sources import flaresolverr, gluetun

log = logging.getLogger("seam.fetch")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Accept-Language": "en-US",
}
api_client = httpx.Client(headers=_HEADERS, timeout=20, follow_redirects=True)
api_aclient = httpx.AsyncClient(headers=_HEADERS, timeout=20, follow_redirects=True)

TIMEOUT = 20
RETRIES = 3
ROTATE_AFTER = 5


class BlockedError(Exception):
    pass


@dataclass
class FetchResult:
    status: int
    headers: Mapping[str, str]
    content: bytes
    url: str
    encoding: Optional[str] = None

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def json(self) -> Any:
        return jsonlib.loads(self.content)

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise RuntimeError(f"HTTP {self.status} for {self.url}")


def _env(name: str) -> str:
    return (os.getenv(name) or "").strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name) or default)
    except ValueError:
        return default


class _Gate:
    def __init__(self, paced: bool):
        self.sem = asyncio.Semaphore(max(1, _env_int("SCRAPE_CONCURRENCY_PER_SOURCE", 3)))
        self.lock = asyncio.Lock()
        self.next_start = 0.0
        self.paced = paced

    async def __aenter__(self):
        await self.sem.acquire()
        if not self.paced:
            return
        try:
            async with self.lock:
                wait = self.next_start - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)
                gap = _env_int("SCRAPE_MIN_INTERVAL_MS", 500) / 1000
                self.next_start = time.monotonic() + gap * (1 + random.uniform(0, 0.5))
        except BaseException:
            self.sem.release()
            raise

    async def __aexit__(self, *exc):
        self.sem.release()


@dataclass
class _State:
    session: AsyncSession
    proxy: str
    gates: dict[tuple[Source, bool], _Gate] = field(default_factory=dict)
    clearance: dict[str, flaresolverr.Clearance] = field(default_factory=dict)


# semaphores and sessions bind to an event loop, so state is kept per loop
_states: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _State]" = weakref.WeakKeyDictionary()
_blocked_streak = 0


def _state() -> _State:
    loop = asyncio.get_running_loop()
    st = _states.get(loop)
    if st is None:
        proxy = _env("SCRAPE_PROXY")
        session = AsyncSession(impersonate="chrome", proxy=proxy or None, headers={"Accept-Language": "en-US"})
        st = _states[loop] = _State(session=session, proxy=proxy)
    return st


def _gate(st: _State, source: Source, paced: bool) -> _Gate:
    if (source, paced) not in st.gates:
        st.gates[source, paced] = _Gate(paced)
    return st.gates[source, paced]


def _is_challenge(status: int, headers: Mapping[str, str], body: bytes) -> bool:
    if (headers.get("cf-mitigated") or "").lower() == "challenge":
        return True
    if status in (403, 503) and "cloudflare" in (headers.get("server") or "").lower() and b"Just a moment" in body:
        return True
    return "html" in (headers.get("content-type") or "") and b"challenges.cloudflare.com" in body


def _retry_after(headers: Mapping[str, str]) -> Optional[float]:
    try:
        return min(float(headers.get("retry-after") or ""), 120.0)
    except ValueError:
        return None


async def _blocked(st: _State, msg: str) -> BlockedError:
    global _blocked_streak
    _blocked_streak += 1
    log.warning("blocked: %s (streak %d)", msg, _blocked_streak)
    if _blocked_streak >= ROTATE_AFTER:
        _blocked_streak = 0
        if await gluetun.rotate():
            st.clearance.clear()
    return BlockedError(msg)


async def fetch(url, *, source: Source, method="GET", params=None, json=None, headers=None, paced=True) -> FetchResult:
    global _blocked_streak
    st = _state()
    domain = urlsplit(url).hostname or ""
    solved = False
    attempt = 0
    while True:
        h = dict(headers or {})
        clear = st.clearance.get(domain)
        if clear:
            h["User-Agent"] = clear.user_agent
        retry_after = None
        try:
            async with _gate(st, source, paced):
                r = await st.session.request(
                    method, url, params=params, json=json, headers=h,
                    cookies=clear.cookies if clear else None, timeout=TIMEOUT,
                )
        except (CurlTimeout, CurlConnectionError) as e:
            why = f"{type(e).__name__} on {url}"
        else:
            res = FetchResult(r.status_code, r.headers, r.content, str(r.url), r.encoding)
            if _is_challenge(res.status, res.headers, res.content[:300_000]):
                if solved or not _env("FLARESOLVERR_URL"):
                    st.clearance.pop(domain, None)
                    raise await _blocked(st, f"challenge on {url}")
                log.info("challenge on %s, solving", domain)
                solution = await flaresolverr.solve(url, st.proxy)
                if solution is None:
                    raise await _blocked(st, f"challenge unsolved on {url}")
                st.clearance[domain] = solution
                solved = True
                continue
            if res.status == 429 or res.status == 403 or res.status >= 500:
                why = f"HTTP {res.status} on {url}"
                retry_after = _retry_after(res.headers) if res.status == 429 else None
            else:
                _blocked_streak = 0
                return res
        if attempt >= RETRIES:
            raise await _blocked(st, f"{why} after {RETRIES} retries")
        delay = retry_after if retry_after is not None else 2**attempt * (1 + random.uniform(0, 0.5))
        log.info("retry %d/%d in %.1fs: %s", attempt + 1, RETRIES, delay, why)
        await asyncio.sleep(delay)
        attempt += 1


async def fetch_bytes(url, *, source: Source) -> tuple[bytes, str]:
    # photos come off image CDNs: own in-flight cap, no spacing, so they don't queue behind page requests
    r = await fetch(url, source=source, paced=False)
    r.raise_for_status()
    return r.content, r.headers.get("content-type") or ""
