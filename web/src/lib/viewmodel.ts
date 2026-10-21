import { bestListing, formatMoney, listingTotalCents } from "@shared/types";
import type { Asset3D, AssetStatus, BodyBase, BodyProfile, Garment, Slot, Transform } from "@shared/types";

export type UiCategory = "tops" | "bottoms" | "outerwear" | "shoes";

export type UiItem = {
  id: string;
  name: string;
  category: UiCategory;
  slot: Slot;
  source: string;
  price: number;
  priceCents: number;
  currency: string;
  priceLabel: string;
  otherStores: { source: string; priceLabel: string }[];
  size?: string;
  condition?: string;
  imageUrl: string;
  listingUrl: string;
  modelUrl?: string;
  anchor?: [number, number, number];
  usableFor3d: boolean;
  followsBodyMorphs: boolean;
  fit?: Transform;
  assetStatus?: AssetStatus;
  converting: boolean;
};

export type TopSize = "XS" | "S" | "M" | "L" | "XL" | "XXL";

export type Profile = {
  heightCm: number;
  weight: number;
  weightUnit: "lb" | "kg";
  base: BodyBase;
  skinTone: string;
  topSize: TopSize;
  bottomSize: string;
  body: { shoulders: number; chest: number; waist: number; hips: number; legs: number };
};

export type Look = { prompt: string; itemIds: string[] };

export const KG_TO_LB = 2.2046;

export const toLb = (weight: number, unit: "lb" | "kg") => (unit === "kg" ? weight * KG_TO_LB : weight);

export const fromLb = (lb: number, unit: "lb" | "kg") => (unit === "kg" ? lb / KG_TO_LB : lb);

export function formatFtIn(cm: number): string {
  const inches = Math.round(cm / 2.54);
  return `${Math.floor(inches / 12)}′ ${inches % 12}″`;
}

const SLOT_LABELS: Record<Slot, UiCategory | null> = {
  top: "tops",
  bottom: "bottoms",
  outer: "outerwear",
  shoes: "shoes",
  onepiece: "tops",
  accessory: null,
};

export function slotLabel(slot: Slot): UiCategory | null {
  return SLOT_LABELS[slot] ?? null;
}

export function isConverting(asset?: Asset3D | null): boolean {
  return asset?.status === "queued" || asset?.status === "processing";
}

export function modelUrlFor(asset: Asset3D | null | undefined, base: BodyBase): string | undefined {
  if (asset?.status !== "ready" || !asset.glb_url) return undefined;
  return base === "fem" && asset.follows_body_morphs ? asset.glb_url.replace(/\.glb$/, "_fem.glb") : asset.glb_url;
}

const storeLabel = (cents: number, currency: string) => formatMoney({ cents, currency });

export function toUiGarment(garment: Garment, base: BodyBase, asset?: Asset3D | null): UiItem | null {
  const { tags } = garment;
  const category = tags ? slotLabel(tags.slot) : null;
  if (!tags || !category) return null;
  const best = bestListing(garment);
  const current = asset === undefined ? garment.asset : asset;
  const priceCents = listingTotalCents(best);
  return {
    id: garment.id,
    name: best.title,
    category,
    slot: tags.slot,
    source: best.source,
    price: priceCents / 100,
    priceCents,
    currency: best.price.currency,
    priceLabel: storeLabel(priceCents, best.price.currency),
    otherStores: garment.listings
      .filter((listing) => listing.status === "active" && listing.id !== best.id)
      .sort((a, b) => listingTotalCents(a) - listingTotalCents(b))
      .map((listing) => ({
        source: listing.source,
        priceLabel: storeLabel(listingTotalCents(listing), listing.price.currency),
      })),
    size: tags.size_normalized ?? best.size_raw ?? undefined,
    condition: best.assessed_condition === "unknown" ? undefined : best.assessed_condition.replace(/_/g, " "),
    imageUrl: tags.clean_image?.url ?? garment.best_photo?.url ?? best.photos[0]?.url ?? "",
    listingUrl: best.url,
    modelUrl: modelUrlFor(current, base),
    usableFor3d: tags.usable_for_3d,
    followsBodyMorphs: current?.follows_body_morphs ?? false,
    fit: current?.fit,
    assetStatus: current?.status,
    converting: tags.usable_for_3d && isConverting(current),
  };
}

const clamp01 = (value: number) => (Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0.5);

export function profileToBody(profile: Profile): BodyProfile {
  const { body } = profile;
  return {
    base: profile.base,
    height: clamp01((profile.heightCm - 140) / 70),
    weight: clamp01((toLb(profile.weight, profile.weightUnit) - 90) / 210),
    muscle: 0.5,
    shoulders: clamp01(body.shoulders / 100),
    chest: clamp01(body.chest / 100),
    waist: clamp01(body.waist / 100),
    hips: clamp01(body.hips / 100),
    leg_length: clamp01(body.legs / 100),
    skin_tone: profile.skinTone,
  };
}
