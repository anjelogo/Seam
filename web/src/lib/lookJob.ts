import type { Category, Item, Slot } from "@shared/types";
import { TEE_PATH } from "../components/brand/tee";
import { easeOut } from "./motion";
import type { Look } from "./viewmodel";

export type { Look };

export type Silhouette = "tee" | "sleeve" | "pants" | "boot" | "skirt" | "shoe" | "belt" | "wallet";

export type Listing = {
  id: string;
  name: string;
  category: "tops" | "bottoms" | "outerwear" | "shoes" | "accessories";
  silhouette: Silhouette;
  source: string;
  price: number;
  size?: string;
  imageUrl: string;
  listingUrl: string;
  color?: string;
};

export type LookJobEvent =
  | { type: "search_started"; sources: string[] }
  | { type: "source_done"; source: string }
  | { type: "listing"; item: Listing; scanned: number }
  | { type: "picked"; itemIds: string[] }
  | { type: "model_started"; itemId: string }
  | { type: "model_progress"; itemId: string; progress: number }
  | { type: "model_ready"; itemId: string; modelUrl: string; anchor: [number, number, number] }
  | { type: "model_failed"; itemId: string }
  | { type: "fitting_started" }
  | { type: "look_ready"; look: Look };

export type Phase = 1 | 2 | 3 | 4 | 5 | "empty" | "timeout";

export type CardState = {
  listing: Listing;
  picked: boolean;
  pickOrder: number | null;
  model: "idle" | "building" | "ready" | "failed";
  progress: number;
};

export type BuildView = {
  phase: Phase;
  prompt: string;
  scanned: number;
  picks: number;
  ready: number;
  stores: number;
  litSource: string | null;
  cards: CardState[];
  pickedNames: string[];
};

// the only stores we scrape
export const STORE_SOURCES = ["ebay", "poshmark", "grailed"];

export const MAX_CARDS = 12;

export const SILHOUETTE_PATHS: Record<Silhouette, string> = {
  tee: TEE_PATH,
  sleeve:
    "M22 10 L12 14 L4 44 L12 46 L18 28 L18 56 L46 56 L46 28 L52 46 L60 44 L52 14 L42 10 C 40 15, 36 17, 32 17 C 28 17, 24 15, 22 10 Z",
  pants: "M18 8 L46 8 L50 56 L37 56 L32 24 L27 56 L14 56 Z",
  boot: "M20 8 L36 8 L36 38 L54 46 L56 56 L18 56 L18 30 Z",
  skirt: "M20 14 L44 14 L52 50 L12 50 Z",
  shoe: "M8 40 C 8 30, 22 28, 30 34 L56 40 L56 50 L8 50 Z",
  belt: "M6 27 L58 27 L58 37 L6 37 Z M28 25 L36 25 L36 39 L28 39 Z",
  wallet: "M14 18 L50 18 L50 46 L14 46 Z",
};

const SILHOUETTE_FOR: Record<Category, Silhouette> = {
  tee: "tee",
  tank: "tee",
  polo: "tee",
  longsleeve: "sleeve",
  button_up: "sleeve",
  sweater: "sleeve",
  hoodie: "sleeve",
  sweatshirt: "sleeve",
  jacket: "sleeve",
  denim_jacket: "sleeve",
  leather_jacket: "sleeve",
  coat: "sleeve",
  vest: "sleeve",
  jeans: "pants",
  pants: "pants",
  cargo: "pants",
  shorts: "pants",
  skirt: "skirt",
  dress: "skirt",
  jumpsuit: "skirt",
  boots: "boot",
  sneakers: "shoe",
  shoes_other: "shoe",
  bag: "wallet",
  hat: "wallet",
  accessory_other: "wallet",
  unknown: "tee",
};

const CATEGORY_FOR: Record<Slot, Listing["category"]> = {
  top: "tops",
  outer: "outerwear",
  bottom: "bottoms",
  onepiece: "tops",
  shoes: "shoes",
  accessory: "accessories",
};

const HEX = /^#?(?:[0-9a-f]{3}){1,2}$/i;

export const silhouetteFor = (category: Category): Silhouette => SILHOUETTE_FOR[category] ?? "tee";

// tags.clean_image urls point at transparent cutouts
export const isCutout = (url: string) => url.startsWith("/static/clean/");

function colorOf(item: Item) {
  const hex = item.tags?.colors[0]?.hex.trim() ?? "";
  if (!HEX.test(hex)) return undefined;
  return hex.startsWith("#") ? hex : `#${hex}`;
}

export function toListing(item: Item): Listing {
  const { listing, tags } = item;
  return {
    id: item.id,
    name: listing.title,
    category: tags ? CATEGORY_FOR[tags.slot] : "tops",
    silhouette: silhouetteFor(tags?.category ?? "unknown"),
    source: listing.source,
    price: listing.price.cents / 100,
    size: tags?.size_normalized ?? listing.size_raw ?? undefined,
    imageUrl: tags?.clean_image?.url ?? listing.images[0]?.url ?? "",
    listingUrl: listing.url,
    color: colorOf(item),
  };
}

const count = (n: number, one: string, many: string) => `${n.toLocaleString("en-US")} ${n === 1 ? one : many}`;

export function phaseCopy({ phase, scanned, picks, ready, stores }: BuildView): { title: string; sub: string } {
  switch (phase) {
    case 1:
      return { title: "searching every store", sub: `${count(scanned, "listing", "listings")} scanned` };
    case 2:
      return { title: "picking your pieces", sub: `${count(picks, "match", "matches")} for your vibe` };
    case 3:
      return { title: "building them in 3d", sub: `${ready} of ${picks} ready` };
    case 4:
      return { title: "dressing you", sub: `fitting ${count(picks, "piece", "pieces")} to your avatar` };
    case 5:
      return { title: "your look is ready.", sub: `${count(picks, "piece", "pieces")} · ${count(stores, "store", "stores")}` };
    case "empty":
      return { title: "nothing fit that vibe.", sub: "" };
    case "timeout":
      return { title: "that took too long.", sub: "" };
  }
}

export function overallProgress({ phase, cards }: BuildView): number {
  if (phase === 1) return 0.25 * Math.min(1, cards.length / MAX_CARDS);
  if (phase === 2) return 0.3;
  if (phase === 3) {
    const picked = cards.filter((card) => card.picked);
    const done = picked.reduce((sum, card) => sum + (card.model === "ready" || card.model === "failed" ? 1 : card.progress), 0);
    return 0.3 + 0.55 * (picked.length ? done / picked.length : 0);
  }
  if (phase === 4) return 0.9;
  return phase === 5 ? 1 : 0;
}

export type BuildFailure = Extract<Phase, "empty" | "timeout">;

export type BuildLog = {
  prompt: string;
  events: LookJobEvent[];
  // when each event arrived, on the same clock as deriveView's now
  times: number[];
  failure: BuildFailure | null;
};

type Build = Pick<CardState, "model" | "progress">;

const COUNT_UP_MS = 2800;
const CHIP_MS = 600;
const IDLE_BUILD: Build = { model: "idle", progress: 0 };

const STAGE_FOR: Partial<Record<LookJobEvent["type"], 2 | 3 | 4 | 5>> = {
  picked: 2,
  model_started: 3,
  model_ready: 3,
  model_failed: 3,
  fitting_started: 4,
  look_ready: 5,
};

const isDone = (build?: Build) => build?.model === "ready" || build?.model === "failed";

// a full grid only takes picks, over its lowest-ranked other card
function place(cards: Listing[], listing: Listing, picked: string[]) {
  if (cards.some((card) => card.id === listing.id)) return;
  if (cards.length < MAX_CARDS) {
    cards.push(listing);
    return;
  }
  const slot = picked.includes(listing.id) ? cards.findLastIndex((card) => !picked.includes(card.id)) : -1;
  if (slot >= 0) cards[slot] = listing;
}

export function deriveView({ prompt, events, times, failure }: BuildLog, now: number): BuildView {
  let picked: string[] = [];
  for (const event of events) if (event.type === "picked") picked = event.itemIds;
  const cards: Listing[] = [];
  const listings = new Map<string, Listing>();
  const builds = new Map<string, Build>();
  const doneSources = new Set<string>();
  let sources: string[] = [];
  let searchAt = now;
  let firstAt: number | null = null;
  let target = 0;
  let stage: 1 | 2 | 3 | 4 | 5 = 1;
  for (const [i, event] of events.entries()) {
    const next = STAGE_FOR[event.type] ?? 1;
    if (next > stage) stage = next;
    switch (event.type) {
      case "search_started":
        sources = event.sources;
        searchAt = times[i];
        break;
      case "source_done":
        doneSources.add(event.source);
        break;
      case "listing":
        target = Math.max(target, event.scanned);
        firstAt ??= times[i];
        listings.set(event.item.id, event.item);
        place(cards, event.item, picked);
        break;
      case "model_started":
        builds.set(event.itemId, { model: "building", progress: 0 });
        break;
      case "model_progress":
        if (!isDone(builds.get(event.itemId))) builds.set(event.itemId, { model: "building", progress: event.progress });
        break;
      case "model_ready":
        builds.set(event.itemId, { model: "ready", progress: 1 });
        break;
      case "model_failed":
        builds.set(event.itemId, { model: "failed", progress: 0 });
        break;
    }
  }
  const phase: Phase = failure ?? stage;
  const searching = sources.filter((source) => !doneSources.has(source));
  const lit = Math.floor(Math.max(0, now - searchAt) / CHIP_MS);
  const chosen = picked.flatMap((id) => listings.get(id) ?? []);
  return {
    phase,
    prompt,
    scanned: phase === 1 && firstAt !== null ? Math.round(target * easeOut((now - firstAt) / COUNT_UP_MS)) : target,
    picks: picked.length,
    ready: picked.filter((id) => isDone(builds.get(id))).length,
    stores: new Set(chosen.map((listing) => listing.source)).size,
    litSource: phase === 1 && searching.length ? searching[lit % searching.length] : null,
    cards: cards.map((listing) => {
      const order = picked.indexOf(listing.id);
      return { listing, picked: order >= 0, pickOrder: order >= 0 ? order : null, ...(builds.get(listing.id) ?? IDLE_BUILD) };
    }),
    pickedNames: chosen.map((listing) => listing.name),
  };
}
