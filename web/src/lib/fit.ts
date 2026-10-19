import type { Fit, Item, Slot } from "@shared/types";
import type { Profile } from "./viewmodel";

export type GarmentFit = { ease: number; crop: number; sizeDelta: number | null };

const EASE: Record<Fit, number> = { slim: 0, regular: 0.15, cropped: 0.15, unknown: 0.15, relaxed: 0.45, oversized: 0.8 };
const BAGGY = /baggy|wide.?leg|oversized|boxy/i;
const LETTER_SLOTS: Slot[] = ["top", "outer", "onepiece"];
// whole tokens only: never the s in men's or the l in slim
const LETTER = /(?<!\w['’]?)(?:(\d)x|(x*))[\s-]*(s|sm|small|m|md|med|medium|l|lg|large)(?!\w)/;

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

// 0..5 on xs s m l xl xxl; each x, or the 2 in 2xl, is one more step from m
function letterIndex(raw: string | null | undefined): number | null {
  const match = raw?.toLowerCase().replace(/e?xtra[\s-]*/g, "x").match(LETTER);
  if (!match) return null;
  const [, digit, xs, size] = match;
  const steps = 1 + (digit ? Number(digit) : xs.length);
  return Math.min(5, Math.max(0, 2 + (size[0] === "s" ? -steps : size[0] === "l" ? steps : 0)));
}

function waist(raw: string | null | undefined): number | null {
  const inches = Number(raw?.match(/\d+/)?.[0]);
  return inches >= 22 && inches <= 50 ? inches : null;
}

const sizesApart = (item: number | null, user: number | null, unit: number) =>
  item === null || user === null ? null : Math.sign(item - user) * Math.round(Math.abs(item - user) / unit) || 0;

function sizeDelta(slot: Slot, raw: string | null | undefined, profile: Profile): number | null {
  if (slot === "bottom") return sizesApart(waist(raw), waist(profile.bottomSize), 2);
  return LETTER_SLOTS.includes(slot) ? sizesApart(letterIndex(raw), letterIndex(profile.topSize), 1) : null;
}

export function garmentFit(item: Item, profile: Profile): GarmentFit {
  const { listing, tags } = item;
  if (!tags) return { ease: EASE.unknown, crop: 0, sizeDelta: null };
  const baggy = [listing.title, ...tags.style_tags].some((text) => BAGGY.test(text));
  const ease = Math.max(EASE[tags.fit] ?? EASE.unknown, baggy ? 0.7 : 0);
  const delta = sizeDelta(tags.slot, tags.size_normalized ?? listing.size_raw, profile);
  const steps = delta ?? 0;
  return {
    ease: clamp01(ease + (steps > 0 ? 0.18 : 0.1) * steps),
    crop: clamp01(-0.3 * steps),
    sizeDelta: delta,
  };
}

export function sizeNote(delta: number | null): string | null {
  if (delta === null) return null;
  if (delta <= -1) return "runs small for you";
  return delta >= 1 ? "runs large for you" : null;
}
