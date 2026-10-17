import type { AssetStatus, BodyBase, Slot, Transform } from "@shared/types";

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
  size?: string;
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
  body: { shoulders: number; chest: number; waist: number; hips: number; legs: number };
};

export type Look = { prompt: string; itemIds: string[] };
