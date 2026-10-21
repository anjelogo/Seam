import { formatMoney, SLOT_LAYER_ORDER } from "@shared/types";
import type { Asset3D, BodyBase, Garment, GenJob, Outfit, OutfitResponseV3, Slot, StyleQuery } from "@shared/types";
import { useMemo } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { getGarment, getLooks, pollGenJob, postGenJob, postLook, postOutfits } from "../lib/api";
import { slotLabel, toUiGarment } from "../lib/viewmodel";
import type { Look, UiItem } from "../lib/viewmodel";
import { useProfile } from "./profile";
import { safeStorage } from "./storage";

type LookState = {
  prompt: string;
  outfits: Outfit[];
  items: Record<string, Garment>;
  worn: string[];
  assets: Record<string, Asset3D>;
  saved: Look[];
  building: boolean;
  lastError: string | null;
  build(prompt: string): Promise<void>;
  toggle(id: string): void;
  takeOff(id: string): void;
  wearLook(look: Look): Promise<void>;
  addItems(items: Garment[]): void;
  ensureAssets(): void;
  clearError(): void;
};

type Dressed = Pick<LookState, "items" | "outfits" | "worn" | "assets" | "saved">;
type Persisted = Dressed & Pick<LookState, "prompt">;

const EMPTY_LOOK: Persisted = { prompt: "", outfits: [], items: {}, worn: [], assets: {}, saved: [] };

const promptOf = (persisted: unknown) => {
  const prompt = (persisted as { prompt?: unknown } | null)?.prompt;
  return typeof prompt === "string" ? prompt : "";
};

const SAVED_LIMIT = 12;
const converting = new Set<string>();
let buildSeq = 0;

function slotOf(garment: Garment | undefined): Slot | null {
  const slot = garment?.tags?.slot;
  return slot && slotLabel(slot) ? slot : null;
}

function conflicts(next: Slot, worn: Slot | null) {
  if (next === worn) return true;
  if (next === "onepiece") return worn === "top" || worn === "bottom";
  return worn === "onepiece" && (next === "top" || next === "bottom");
}

const sameIds = (a: string[], b: string[]) => a.length === b.length && a.every((id) => b.includes(id));

function styleQuery(prompt: string): StyleQuery {
  const { profile, bodyProfile } = useProfile.getState();
  return {
    prompt,
    budget: null,
    sizes: { top: profile?.topSize ?? null, bottom: profile?.bottomSize ?? null },
    slots: ["top", "bottom", "outer", "shoes"],
    sources: [],
    num_outfits: 3,
    require_3d_ready: false,
    body: bodyProfile(),
    previous_outfit_ids: [],
    feedback: null,
  };
}

export const requestOutfits = (prompt: string) => postOutfits(styleQuery(prompt));

function wearOutfit(state: LookState, prompt: string, res: OutfitResponseV3): Dressed | null {
  const outfit = res.outfits[0];
  if (!outfit) return null;
  const items = { ...state.items, ...res.garments };
  const ids = SLOT_LAYER_ORDER.map((slot) => outfit.pieces[slot]?.item_id);
  const worn = [...new Set(ids)].filter((id): id is string => !!id && slotOf(items[id]) !== null);
  if (!worn.length) return null;
  const assets = { ...state.assets };
  for (const garment of Object.values(res.garments)) {
    const keepReady = assets[garment.id]?.status === "ready" && garment.asset?.status !== "ready";
    if (garment.asset && !keepReady) assets[garment.id] = garment.asset;
  }
  const others = state.saved.filter((look) => look.prompt !== prompt || !sameIds(look.itemIds, worn));
  const saved = [{ prompt, itemIds: worn }, ...others].slice(0, SAVED_LIMIT);
  return { items, outfits: res.outfits, worn, assets, saved };
}

const saveLook = (look: Look) => void postLook(look).catch(() => {});

export function applyOutfit(prompt: string, res: OutfitResponseV3): string[] | null {
  const next = wearOutfit(useLook.getState(), prompt, res);
  if (!next) return null;
  useLook.setState({ ...next, prompt });
  saveLook(next.saved[0]);
  return next.worn;
}

export async function fetchSaved() {
  try {
    const looks = await getLooks();
    useLook.setState({ saved: looks.map(({ prompt, itemIds }) => ({ prompt, itemIds })) });
  } catch {}
}

export const clearSaved = () => useLook.setState({ saved: [] });

export const conversionPending = (id: string) => converting.has(id);

const setAsset = (id: string, asset: Asset3D) => useLook.setState((s) => ({ assets: { ...s.assets, [id]: asset } }));

async function convert(job: GenJob) {
  const id = job.item_id;
  converting.add(id);
  try {
    const asset = await postGenJob(job);
    setAsset(id, asset);
    if (asset.status !== "ready" && asset.status !== "failed") await pollGenJob(id, (next) => setAsset(id, next));
  } catch {
    const { assets, items } = useLook.getState();
    const prev = assets[id] ?? items[id]?.asset;
    if (prev) setAsset(id, { ...prev, status: "failed", error: "3d conversion failed" });
  } finally {
    converting.delete(id);
  }
}

export const useLook = create<LookState>()(
  persist(
    (set, get) => ({
      prompt: "",
      outfits: [],
      items: {},
      worn: [],
      assets: {},
      saved: [],
      building: false,
      lastError: null,
      build: async (raw) => {
        const prompt = raw.trim();
        if (!prompt) return;
        const seq = ++buildSeq;
        set({ building: true, lastError: null, prompt });
        try {
          const res = await requestOutfits(prompt);
          if (seq !== buildSeq) return;
          const next = wearOutfit(get(), prompt, res);
          if (!next) {
            set({ building: false, lastError: "no pieces matched that vibe. try another." });
            return;
          }
          set({ ...next, building: false });
          saveLook(next.saved[0]);
        } catch {
          if (seq === buildSeq) set({ building: false, lastError: "couldn't build that look. try again." });
          return;
        }
        get().ensureAssets();
      },
      toggle: (id) => {
        const { worn, items } = get();
        if (worn.includes(id)) return get().takeOff(id);
        const slot = slotOf(items[id]);
        if (!slot) return;
        set({ worn: [...worn.filter((w) => !conflicts(slot, slotOf(items[w]))), id] });
        get().ensureAssets();
      },
      takeOff: (id) => set((s) => ({ worn: s.worn.filter((w) => w !== id) })),
      wearLook: async (look) => {
        // looks synced from another device may name garments not cached here, or pre-v3 listing ids
        const missing = look.itemIds.filter((id) => !get().items[id]);
        const fetched = await Promise.all(missing.map(async (id) => [id, await getGarment(id).catch(() => null)] as const));
        get().addItems(fetched.flatMap(([, garment]) => garment ?? []));
        const resolved = new Map(fetched.flatMap(([id, garment]) => (garment ? [[id, garment.id] as const] : [])));
        const ids = [...new Set(look.itemIds.map((id) => resolved.get(id) ?? id))];
        set((s) => ({ prompt: look.prompt, worn: ids.filter((id) => slotOf(s.items[id]) !== null) }));
        get().ensureAssets();
      },
      addItems: (list) =>
        set((s) => {
          const items = { ...s.items };
          const assets = { ...s.assets };
          for (const garment of list) {
            items[garment.id] = garment;
            if (garment.asset && !assets[garment.id]) assets[garment.id] = garment.asset;
          }
          return { items, assets };
        }),
      ensureAssets: () => {
        const { worn, items, assets } = get();
        for (const id of worn) {
          const tags = items[id]?.tags;
          const status = (assets[id] ?? items[id]?.asset)?.status;
          if (!tags?.usable_for_3d || !tags.clean_image || converting.has(id)) continue;
          if (status === "ready" || status === "failed") continue;
          void convert({
            item_id: id,
            image_url: tags.clean_image.url,
            category: tags.category,
            tier: "template_textured",
            resolution: 512,
          });
        }
      },
      clearError: () => set({ lastError: null }),
    }),
    {
      name: "seam.look",
      version: 3,
      storage: safeStorage,
      partialize: ({ prompt, outfits, items, worn, assets, saved }) => ({ prompt, outfits, items, worn, assets, saved }),
      // older blobs name listings, not garments: nothing but the prompt survives
      migrate: (persisted) => ({ ...EMPTY_LOOK, prompt: promptOf(persisted) }),
    },
  ),
);

// resume conversions left running before a reload
useLook.getState().ensureAssets();

const useBase = () => useProfile((s) => s.profile?.base ?? "masc");

const layer = (item: UiItem) => SLOT_LAYER_ORDER.indexOf(item.slot);

function uiItem(garment: Garment | undefined, base: BodyBase, assets: Record<string, Asset3D>) {
  return garment ? toUiGarment(garment, base, assets[garment.id] ?? garment.asset) : null;
}

export function useWornItems(): UiItem[] {
  const base = useBase();
  const worn = useLook((s) => s.worn);
  const items = useLook((s) => s.items);
  const assets = useLook((s) => s.assets);
  return useMemo(
    () => worn.flatMap((id) => uiItem(items[id], base, assets) ?? []).sort((a, b) => layer(a) - layer(b)),
    [worn, items, assets, base],
  );
}

export function useUiItem(id: string | null): UiItem | null {
  const base = useBase();
  const garment = useLook((s) => (id ? s.items[id] : undefined));
  const asset = useLook((s) => (id ? s.assets[id] : undefined));
  return useMemo(() => (garment ? toUiGarment(garment, base, asset ?? garment.asset) : null), [garment, asset, base]);
}

export function useUiItems(list: Garment[]): UiItem[] {
  const base = useBase();
  const assets = useLook((s) => s.assets);
  return useMemo(() => list.flatMap((item) => uiItem(item, base, assets) ?? []), [list, assets, base]);
}

export function useWornTotal(): { count: number; cents: number; label: string } {
  const worn = useWornItems();
  return useMemo(() => {
    const cents = worn.reduce((sum, item) => sum + item.priceCents, 0);
    return { count: worn.length, cents, label: formatMoney({ cents, currency: "USD" }) };
  }, [worn]);
}
