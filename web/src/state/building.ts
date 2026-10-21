import { useGLTF } from "@react-three/drei";
import type { Asset3D, BodyBase, Garment, Slot } from "@shared/types";
import { create } from "zustand";
import { getGarments } from "../lib/api";
import { deriveView, MAX_CARDS, STORE_SOURCES, toListing } from "../lib/lookJob";
import type { BuildFailure, BuildLog, BuildView, LookJobEvent } from "../lib/lookJob";
import { toUiGarment } from "../lib/viewmodel";
import { applyOutfit, conversionPending, requestOutfits, useLook } from "./look";
import { DEFAULT_PROFILE, useProfile } from "./profile";

type BuildingState = {
  view: BuildView;
  events: LookJobEvent[];
  start(prompt: string): void;
  retry(prompt: string): void;
  cancel(): void;
};

type Ready = Extract<LookJobEvent, { type: "model_ready" }>;
type Settled = Ready | Extract<LookJobEvent, { type: "model_failed" }>;
type Flipped = { at: number; shown: number; ready: Ready | null };

const TICK_MS = 100;
const TIMEOUT_MS = 60000;
const HOLD_SEARCH_MS = 1500;
const HOLD_PICK_MS = 1200;
const HOLD_FIT_MS = 1200;
const CARD_DELAY_MS = 150;
const CARD_STAGGER_MS = 220;
const FLIP_STAGGER_MS = 800;
const READY_FILL_MS = 1200;
const CONVERT_MS = 55000;
const CONVERT_CAP = 0.9;
const BUILD_CAP_MS = 40000;
const SETTLE_MS = 600;
const FIT_CAP_MS = 3000;
const PROGRESS_STEP = 0.01;
const ITEMS_LIMIT = 50;
// same fallbacks Garment.tsx draws
const TEMPLATE_FOR_SLOT: Partial<Record<Slot, string>> = {
  top: "tee_v1",
  outer: "jacket_v1",
  bottom: "pants_v1",
  onepiece: "dress_v1",
};

const IDLE: BuildLog = { prompt: "", events: [], times: [], failure: null };
const IDLE_VIEW = deriveView(IDLE, 0);

let log = IDLE;
let shown = JSON.stringify(IDLE_VIEW);
let runId = 0;
let timers: number[] = [];
let ticker = 0;

const now = () => performance.now();

const currentBase = (): BodyBase => useProfile.getState().profile?.base ?? DEFAULT_PROFILE.base;

const notFound = (error: unknown) => (error as { status?: unknown } | null)?.status === 404;

const rank = ({ tags }: Garment) => (!tags ? 2 : tags.usable_for_3d && tags.clean_image ? 0 : 1);

const bestCards = (garments: Garment[]) => [...garments].sort((a, b) => rank(a) - rank(b)).slice(0, MAX_CARDS);

function later(ms: number, fn: () => void) {
  const timer = window.setTimeout(fn, ms);
  timers.push(timer);
  return timer;
}

const wait = (ms: number) => new Promise<void>((resolve) => later(ms, resolve));

function halt() {
  runId++;
  for (const timer of timers) window.clearTimeout(timer);
  timers = [];
  window.clearInterval(ticker);
}

function publish() {
  const view = deriveView(log, now());
  const key = JSON.stringify(view);
  if (key === shown && useBuilding.getState().events === log.events) return;
  useBuilding.setState(key === shown ? { events: log.events } : { events: log.events, view });
  shown = key;
}

function emit(event: LookJobEvent) {
  log = { ...log, events: [...log.events, event], times: [...log.times, now()] };
  publish();
}

function fail(failure: BuildFailure) {
  halt();
  log = { ...log, failure };
  publish();
}

async function listings(prompt: string) {
  const res = await getGarments({ q: prompt, limit: ITEMS_LIMIT });
  return res.garments.length ? res : getGarments({ limit: ITEMS_LIMIT });
}

// the event that settles a piece now, or null while it still converts
function verdict(itemId: string): Settled | null {
  const { items, assets } = useLook.getState();
  const garment = items[itemId];
  const asset = assets[itemId] ?? garment?.asset;
  const ui = garment ? toUiGarment(garment, currentBase(), asset) : null;
  if (ui?.modelUrl) return { type: "model_ready", itemId, modelUrl: ui.modelUrl, anchor: ui.anchor ?? [0, 0, 0] };
  const status = asset?.status;
  const usable = garment?.tags?.usable_for_3d && garment.tags.clean_image;
  if (usable && status !== "ready" && status !== "failed" && conversionPending(itemId)) return null;
  return { type: "model_failed", itemId };
}

function openModelUrl(asset: Asset3D | null | undefined, base: BodyBase) {
  if (asset?.status !== "ready" || !asset.glb_url) return undefined;
  return asset.glb_url.replace(/\.glb$/, base === "fem" && asset.follows_body_morphs ? "_open_fem.glb" : "_open.glb");
}

// every GLB the avatar may draw for these pieces, open jackets included
function garmentUrls(ids: string[], base: BodyBase) {
  const { items, assets } = useLook.getState();
  const slots = new Set(ids.map((id) => items[id]?.tags?.slot));
  const layered = slots.has("top") || slots.has("onepiece");
  const urls = new Set<string>();
  for (const id of ids) {
    const garment = items[id];
    const asset = assets[id] ?? garment?.asset;
    const ui = garment ? toUiGarment(garment, base, asset) : null;
    if (!ui) continue;
    const template = asset?.template_id ?? TEMPLATE_FOR_SLOT[ui.slot];
    const open = layered && ui.slot === "outer";
    const candidates = [
      ui.modelUrl,
      template ? `/assets/templates/${template}_${base}.glb` : undefined,
      open ? openModelUrl(asset, base) : undefined,
      open && template ? `/assets/templates/${template}_open_${base}.glb` : undefined,
    ];
    for (const url of candidates) if (url) urls.add(url);
  }
  return [...urls];
}

// reads drei's cache; throws the pending load until it settles
async function loaded(url: string) {
  for (;;) {
    try {
      useGLTF(url, false);
      return;
    } catch (pending) {
      if (!(pending instanceof Promise)) return;
      await pending;
    }
  }
}

// TODO(anjelo): swap for sse stream
function orchestrate(prompt: string) {
  const run = runId;
  const live = () => run === runId;
  const listed = new Set<string>();
  const flipped = new Map<string, Flipped>();
  const settled = new Set<string>();
  let worn: string[] = [];
  let scanned = 0;
  let searched = false;
  let held = false;
  let picked = false;
  let fitting = false;

  const timeout = later(TIMEOUT_MS, () => fail("timeout"));
  later(HOLD_SEARCH_MS, () => {
    held = true;
    toPicked();
  });
  // a macrotask late, so a strict mode remount never posts /outfits twice
  later(0, () => {
    void search();
    void pick();
  });
  ticker = window.setInterval(tick, TICK_MS);

  async function search() {
    const res = await listings(prompt).catch(() => null);
    if (!live()) return;
    scanned = res?.total ?? 0;
    const garments = res ? bestCards(res.garments) : [];
    garments.forEach((garment, i) =>
      later(CARD_DELAY_MS + CARD_STAGGER_MS * i, () => {
        listed.add(garment.id);
        emit({ type: "listing", item: toListing(garment), scanned });
        if (i === garments.length - 1) found();
      }),
    );
    if (!garments.length) found();
  }

  function found() {
    searched = true;
    toPicked();
  }

  async function pick() {
    const res = await requestOutfits(prompt).catch((error: unknown) => {
      if (live()) fail(notFound(error) ? "empty" : "timeout");
      return null;
    });
    if (!res || !live()) return;
    const ids = applyOutfit(prompt, res);
    if (!ids) return fail("empty");
    worn = ids;
    useLook.getState().ensureAssets();
    for (const source of STORE_SOURCES) emit({ type: "source_done", source });
    toPicked();
  }

  function toPicked() {
    if (picked || !worn.length || !searched || !held) return;
    picked = true;
    window.clearTimeout(timeout);
    emit({ type: "picked", itemIds: worn });
    const { items } = useLook.getState();
    for (const id of worn) if (!listed.has(id) && items[id]) emit({ type: "listing", item: toListing(items[id]), scanned });
    later(HOLD_PICK_MS, toBuilding);
  }

  function toBuilding() {
    const queue: string[] = [];
    for (const itemId of worn) {
      const result = verdict(itemId);
      if (result?.type === "model_failed") settle(result);
      else queue.push(itemId);
    }
    queue.forEach((itemId, k) => later(FLIP_STAGGER_MS * k, () => flip(itemId)));
    later(BUILD_CAP_MS, toFitting);
  }

  function flip(itemId: string) {
    if (fitting) return;
    const result = verdict(itemId);
    if (result?.type === "model_failed") return settle(result);
    emit({ type: "model_started", itemId });
    flipped.set(itemId, { at: now(), shown: 0, ready: result });
  }

  function tick() {
    if (!fitting) for (const [itemId, card] of [...flipped]) step(itemId, card);
    publish();
  }

  function step(itemId: string, card: Flipped) {
    const elapsed = now() - card.at;
    if (card.ready) {
      if (elapsed >= READY_FILL_MS) settle(card.ready);
      else advance(itemId, card, elapsed / READY_FILL_MS);
      return;
    }
    const result = verdict(itemId);
    if (result) settle(result);
    else advance(itemId, card, CONVERT_CAP * Math.min(1, elapsed / CONVERT_MS));
  }

  function advance(itemId: string, card: Flipped, progress: number) {
    if (progress - card.shown < PROGRESS_STEP) return;
    card.shown = progress;
    emit({ type: "model_progress", itemId, progress });
  }

  function settle(event: Settled) {
    flipped.delete(event.itemId);
    settled.add(event.itemId);
    emit(event);
    if (settled.size === worn.length) later(SETTLE_MS, toFitting);
  }

  function toFitting() {
    if (fitting) return;
    fitting = true;
    emit({ type: "fitting_started" });
    const urls = garmentUrls(worn, currentBase());
    for (const url of urls) useGLTF.preload(url, false);
    const fitted = Promise.race([Promise.all(urls.map(loaded)), wait(FIT_CAP_MS)]);
    void Promise.all([fitted, wait(HOLD_FIT_MS)]).then(() => {
      if (!live()) return;
      emit({ type: "look_ready", look: { prompt, itemIds: worn } });
      halt();
    });
  }
}

export const useBuilding = create<BuildingState>()((_, get) => ({
  view: IDLE_VIEW,
  events: IDLE.events,
  start: (raw) => {
    halt();
    const prompt = raw.trim();
    log = { ...IDLE, prompt };
    if (!prompt) return fail("empty");
    emit({ type: "search_started", sources: STORE_SOURCES });
    orchestrate(prompt);
  },
  retry: (prompt) => get().start(prompt),
  cancel: () => {
    halt();
    log = IDLE;
    publish();
  },
}));
