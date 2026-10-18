import json
import os
import re
import secrets
import time
from typing import Optional

import anthropic
from pydantic import BaseModel
from seam_shared.models import AssetStatus, BodyProfile, Item, Money, Outfit, OutfitPiece, OutfitResponse, Slot, StyleQuery

from app import db

MODEL = "claude-sonnet-5-5"
PER_SLOT = 30
BODY_WORDS = {
    "height": ("short", "tall"), "weight": ("slim build", "heavier build"), "muscle": ("lean", "muscular"),
    "shoulders": ("narrow shoulders", "broad shoulders"), "chest": ("flat chest", "full chest"),
    "waist": ("narrow waist", "wide waist"), "hips": ("narrow hips", "wide hips"), "leg_length": ("short legs", "long legs"),
}


class Pick(BaseModel):
    slot: Slot
    item_id: str
    reason: str
    alternates: list[str]


class Look(BaseModel):
    name: str
    vibe_summary: str
    pieces: list[Pick]


class Looks(BaseModel):
    outfits: list[Look]


def cost(item: Item) -> int:
    return item.listing.price.cents + (item.listing.shipping.cents if item.listing.shipping else 0)


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _candidates(conn, query: StyleQuery, cap: Optional[int], text: str) -> dict[Slot, list[Item]]:
    """Per requested slot, the PER_SLOT best items: size match first, then prompt overlap, then cheapest."""
    want = _words(text)
    sizes = {Slot.top: query.sizes.top, Slot.outer: query.sizes.top, Slot.onepiece: query.sizes.top,
             Slot.bottom: query.sizes.bottom, Slot.shoes: query.sizes.shoes}
    pools = {}
    for slot in query.slots:
        size = (sizes.get(slot) or "").upper().replace(" ", "")
        hits = [
            i for i in db.items(conn, "WHERE json_extract(tags, '$.slot') = ?", (slot.value,))
            if (not query.sources or i.listing.source in query.sources)
            and (cap is None or cost(i) <= cap)
            and (not query.require_3d_ready or (i.asset and i.asset.status == AssetStatus.ready))
        ]

        # shortcut: size match ranks first instead of filtering so a thin slot still fills; filter hard once inventory is a few hundred per slot
        def rank(i: Item):
            t = i.tags
            hay = _words(" ".join([i.listing.title, t.category.value, t.era or "", t.pattern or "", t.material or "", *t.style_tags, *(c.name for c in t.colors)]))
            return bool(size) and (t.size_normalized or "").upper() == size, len(want & hay), -cost(i)

        pools[slot] = sorted(hits, key=rank, reverse=True)[:PER_SLOT]
    return pools


def _body(body: BodyProfile) -> str:
    traits = [BODY_WORDS[k][v > 0.5] for k, v in body.model_dump(include=set(BODY_WORDS)).items() if round(abs(v - 0.5), 2) >= 0.1]
    return ", ".join([f"{body.base.value} frame", *traits])


def _prompt(query: StyleQuery, pools: dict[Slot, list[Item]], cap: Optional[int], previous: list[Outfit], by_id: dict, short: dict[str, str]) -> str:
    rows = [
        json.dumps({"id": short[i.id], "slot": s.value, "category": i.tags.category.value, "colors": [c.name for c in i.tags.colors],
                    "style_tags": i.tags.style_tags, "era": i.tags.era, "fit": i.tags.fit.value, "price_usd": cost(i) / 100, "title": i.listing.title[:90]})
        for s, items in pools.items() for i in items
    ]
    lines = [
        "You are a thrift stylist. Build outfits only from the candidate listings below.",
        f"Style prompt: {query.prompt}",
        f"Budget per outfit: ${cap / 100:.2f} including shipping" if cap is not None else "No budget cap.",
        f"Slots: {', '.join(s.value for s in pools)}",
    ]
    if query.body:
        lines.append(f"Wearer's body: {_body(query.body)}. Each reason also says how the piece works on this body.")
    if previous:
        lines.append("Previous outfits the user saw:")
        lines += [f"- {o.name}: " + "; ".join(f"{s.value}={by_id[p.item_id].listing.title[:60] if p.item_id in by_id else p.item_id}" for s, p in o.pieces.items()) + f" (total ${o.total.cents / 100:.2f})" for o in previous]
    if query.feedback:
        lines.append(f"User feedback on those outfits: \"{query.feedback}\". Build new outfits that clearly apply it.")
    lines += [
        f"Return exactly {query.num_outfits} distinct outfits. Rules:",
        "- one piece per slot listed, using only ids whose candidate slot matches; a onepiece replaces top and bottom",
        "- each outfit's summed price_usd must stay within the budget; aim for 90% of it to leave margin",
        "- reason: why the piece fits the vibe, 15 words max",
        "- alternates: 2-4 other candidate ids from the same slot that would also work",
        "- name: a short evocative outfit name; vibe_summary: one sentence, 25 words max",
        "- vary the items across outfits",
        "Candidates (one JSON per line):",
        *rows,
    ]
    return "\n".join(lines)


def _repair(look: Look, pools: dict[Slot, list[Item]], cap: Optional[int], by_id: dict[str, Item]) -> Outfit:
    """Never trust the LLM: drop invalid picks, fill gaps, enforce onepiece and budget, recompute totals."""
    slot_of = {i.id: s for s, items in pools.items() for i in items}
    picks = {p.slot: p for p in look.pieces if slot_of.get(p.item_id) == p.slot}
    if Slot.onepiece in picks:
        picks.pop(Slot.top, None)
        picks.pop(Slot.bottom, None)
    for s in pools:
        skip = s == Slot.onepiece or (Slot.onepiece in picks and s in (Slot.top, Slot.bottom))
        if s not in picks and not skip and pools[s]:
            picks[s] = Pick(slot=s, item_id=pools[s][0].id, reason="Closest match left in this slot.", alternates=[])

    def cheaper(s: Slot) -> Item:
        """The LLM's cheapest alternate if it saves money (keeps the vibe), else the slot's cheapest item."""
        cur = cost(by_id[picks[s].item_id])
        alts = [by_id[a] for a in picks[s].alternates if slot_of.get(a) == s and cost(by_id[a]) < cur]
        return min(alts or pools[s], key=cost)

    while cap is not None and sum(cost(by_id[p.item_id]) for p in picks.values()) > cap:
        s, swap = max(((s, cheaper(s)) for s in picks), key=lambda sc: cost(by_id[picks[sc[0]].item_id]) - cost(sc[1]))
        if cost(swap) >= cost(by_id[picks[s].item_id]):
            break
        picks[s] = Pick(slot=s, item_id=swap.id, reason="Lower-priced pick that keeps this outfit within budget.", alternates=picks[s].alternates)

    pieces = {}
    for s, p in picks.items():
        alts = [a for a in dict.fromkeys(p.alternates) if a != p.item_id and slot_of.get(a) == s][:4]
        alts += [i.id for i in pools[s] if i.id != p.item_id and i.id not in alts][: max(0, 2 - len(alts))]
        pieces[s] = OutfitPiece(item_id=p.item_id, reason=p.reason, alternates=alts)
    chosen = [by_id[p.item_id] for p in pieces.values()]
    total = sum(map(cost, chosen))
    saved = sum(max(i.tags.est_retail.cents - i.listing.price.cents, 0) for i in chosen if i.tags.est_retail)
    return Outfit(
        id=f"o_{secrets.token_hex(4)}", name=look.name, vibe_summary=look.vibe_summary, pieces=pieces, total=Money(cents=total),
        savings_vs_retail=Money(cents=saved) if saved else None, within_budget=cap is None or total <= cap,
    )


def _ask(prompt: str) -> Looks:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise anthropic.AnthropicError("ANTHROPIC_API_KEY is not set")
    # thinking off: it doubled latency past the 10 s target without better outfits
    msg = anthropic.Anthropic().messages.parse(
        model=MODEL, max_tokens=4096, messages=[{"role": "user", "content": prompt}], output_format=Looks, thinking={"type": "between_tools"}
    )
    return msg.parsed_output


def build(query: StyleQuery) -> OutfitResponse:
    start = time.perf_counter()
    conn = db.connect()
    previous = db.outfits(conn, query.previous_outfit_ids)
    cap = query.budget.cents if query.budget else None
    if previous and query.feedback and "cheap" in query.feedback.lower():
        # "cheaper" means every new outfit costs less than the cheapest one already shown
        lower = int(min(o.total.cents for o in previous) * 0.9)
        cap = min(cap, lower) if cap is not None else lower
    pools = _candidates(conn, query, cap, f"{query.prompt} {query.feedback or ''}")
    if not any(pools.values()):
        conn.close()
        raise LookupError("no tagged items match these slots, sources and budget")
    by_id = {i.id: i for items in pools.values() for i in items}
    # short ids keep the LLM's output small; real ids are ~20 tokens each
    short = {item_id: f"c{n}" for n, item_id in enumerate(by_id)}
    real = {v: k for k, v in short.items()}
    by_id.update({i.id: i for o in previous for p in o.pieces.values() for i in db.items(conn, "WHERE items.id = ?", (p.item_id,))})
    looks = _ask(_prompt(query, pools, cap, previous, by_id, short))
    for p in (p for look in looks.outfits for p in look.pieces):
        p.item_id, p.alternates = real.get(p.item_id, p.item_id), [real.get(a, a) for a in p.alternates]
    outfits = [_repair(look, pools, cap, by_id) for look in looks.outfits[: query.num_outfits]]
    db.save_outfits(conn, outfits)
    conn.commit()
    conn.close()
    used = {i for o in outfits for p in o.pieces.values() for i in (p.item_id, *p.alternates)}
    return OutfitResponse(query=query, outfits=outfits, items={i: by_id[i] for i in used}, took_ms=int((time.perf_counter() - start) * 1000))
