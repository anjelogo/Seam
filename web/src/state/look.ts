import { formatMoney, SLOT_LAYER_ORDER } from "@shared/types";
import type { Asset3D, BodyBase, GenJob, Item, Outfit, OutfitResponse, Slot, StyleQuery } from "@shared/types";
import { useMemo } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { pollGenJob, postGenJob, postOutfits } from "../lib/api";
import { slotLabel, toUiItem } from "../lib/viewmodel";
import type { Look, UiItem } from "../lib/viewmodel";
import { useProfile } from "./profile";
import { safeStorage } from "./storage";

type LookState = {
  prompt: string;
  outfits: Outfit[];
  items: Record<string, Item>;
  worn: string[];
  assets: Record<string, Asset3D>;
  saved: Look[];
  building: boolean;
  lastError: string | null;
  build(prompt: string): Promise<void>;
  toggle(id: string): void;
  takeOff(id: string): void;
  wearLook(look: Look): void;
  addItems(items: Item[]): void;
  ensureAssets(): void;
  clearError(): void;
};

const SAVED_LIMIT = 12;
const converting = new Set<string>();
let buildSeq = 0;

function slotOf(item: Item | undefined): Slot | null {
  const slot = item?.tags?.slot;
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

function wearOutfit(state: LookState, prompt: string, res: OutfitResponse): Partial<LookState> | null {
  const outfit = res.outfits[0];
  if (!outfit) return null;
  const items = { ...state.items, ...res.items };
  const ids = SLOT_LAYER_ORDER.map((slot) => outfit.pieces[slot]?.item_id);
  const worn = [...new Set(ids)].filter((id): id is string => !!id && slotOf(items[id]) !== null);
  if (!worn.length) return null;
  const assets = { ...state.assets };
  for (const item of Object.values(res.items)) {
    const keepReady = assets[item.id]?.status === "ready" && item.asset?.status !== "ready";
    if (item.asset && !keepReady) assets[item.id] = item.asset;
  }
  const others = state.saved.filter((look) => look.prompt !== prompt || !sameIds(look.itemIds, worn));
  const saved = [{ prompt, itemIds: worn }, ...others].slice(0, SAVED_LIMIT);
  return { items, outfits: res.outfits, worn, assets, saved };
}

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
          const res = await postOutfits(styleQuery(prompt));
          if (seq !== buildSeq) return;
          const next = wearOutfit(get(), prompt, res);
          if (!next) {
            set({ building: false, lastError: "no pieces matched that vibe. try another." });
            return;
          }
          set({ ...next, building: false });
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
      wearLook: (look) => {
        set((s) => ({ prompt: look.prompt, worn: look.itemIds.filter((id) => slotOf(s.items[id]) !== null) }));
        get().ensureAssets();
      },
      addItems: (list) =>
        set((s) => {
          const items = { ...s.items };
          const assets = { ...s.assets };
          for (const item of list) {
            items[item.id] = item;
            if (item.asset && !assets[item.id]) assets[item.id] = item.asset;
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
      storage: safeStorage,
      partialize: ({ prompt, outfits, items, worn, assets, saved }) => ({ prompt, outfits, items, worn, assets, saved }),
    },
  ),
);

// resume conversions left running before a reload
useLook.getState().ensureAssets();

const useBase = () => useProfile((s) => s.profile?.base ?? "masc");

const layer = (item: UiItem) => SLOT_LAYER_ORDER.indexOf(item.slot);

function uiItem(item: Item | undefined, base: BodyBase, assets: Record<string, Asset3D>) {
  return item ? toUiItem(item, base, assets[item.id] ?? item.asset) : null;
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
  const item = useLook((s) => (id ? s.items[id] : undefined));
  const asset = useLook((s) => (id ? s.assets[id] : undefined));
  return useMemo(() => (item ? toUiItem(item, base, asset ?? item.asset) : null), [item, asset, base]);
}

export function useUiItems(list: Item[]): UiItem[] {
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
