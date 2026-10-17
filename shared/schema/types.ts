/**
 * Shared contract — TS mirror of shared/schema/models.py.
 * models.py is SOURCE OF TRUTH. Change both in same commit.
 *
 * Money = integer cents. IDs = strings. Item.id = `${source}:${source_id}`.
 */

// ───────────── enums (string unions) ─────────────

export type Source = "ebay" | "depop" | "poshmark" | "grailed" | "mercari" | "other";

export type Slot = "top" | "bottom" | "outer" | "onepiece" | "shoes" | "accessory";

export type Category =
  // tops
  | "tee" | "longsleeve" | "tank" | "button_up" | "polo" | "sweater" | "hoodie" | "sweatshirt"
  // outer
  | "jacket" | "denim_jacket" | "leather_jacket" | "coat" | "vest"
  // bottoms
  | "jeans" | "pants" | "cargo" | "shorts" | "skirt"
  // onepiece
  | "dress" | "jumpsuit"
  // shoes / accessories
  | "sneakers" | "boots" | "shoes_other" | "hat" | "bag" | "accessory_other"
  | "unknown";

export type Condition = "new_with_tags" | "like_new" | "good" | "fair" | "unknown";
export type Fit = "oversized" | "relaxed" | "regular" | "slim" | "cropped" | "unknown";
export type ImageView = "flat_lay" | "hanger" | "mannequin" | "on_model" | "detail" | "unknown";
export type AssetTier = "template_textured" | "generated" | "voxel";
export type AssetStatus = "queued" | "processing" | "ready" | "failed";
export type BodyBase = "masc" | "fem";

// ───────────── primitives ─────────────

export interface Money {
  cents: number;
  currency: string; // "USD"
}

export interface ImageRef {
  url: string;
  local_path?: string | null;
  width?: number | null;
  height?: number | null;
  view: ImageView;
}

export interface Color {
  name: string;
  hex: string;
  ratio: number; // 0..1
}

// ───────────── Caden: ingest ─────────────

export interface Listing {
  source: Source;
  source_id: string;
  url: string;
  title: string;
  description?: string | null;
  price: Money;
  shipping?: Money | null;
  condition: Condition;
  brand?: string | null;
  size_raw?: string | null;
  images: ImageRef[];
  seller?: string | null;
  scraped_at: string; // ISO-8601 UTC
}

// ───────────── Caden: CV / tagging ─────────────

export interface ItemTags {
  slot: Slot;
  category: Category;
  colors: Color[];
  pattern?: string | null;
  material?: string | null;
  fit: Fit;
  style_tags: string[];
  era?: string | null;
  size_normalized?: string | null;
  confidence: number;
  est_retail?: Money | null;   // v2
  tagger?: string | null;      // v2
  clean_image?: ImageRef | null;
  best_view_index: number;
  garment_box?: [number, number, number, number] | null; // v2: 0..1 in images[best_view_index]
  usable_for_3d: boolean;
  unusable_reason?: string | null;
}

export interface Item {
  id: string;
  listing: Listing;
  tags?: ItemTags | null;
  asset?: Asset3D | null;
}

// ───────────── Caden: outfit LLM ─────────────

export interface SizeProfile {
  top?: string | null;
  bottom?: string | null;
  shoes?: string | null;
}

export interface StyleQuery {
  prompt: string;
  budget?: Money | null;
  sizes: SizeProfile;
  slots: Slot[];
  sources: Source[];
  num_outfits: number;
  require_3d_ready: boolean;
  body?: BodyProfile | null;      // v2
  previous_outfit_ids: string[];  // v2: refine
  feedback?: string | null;       // v2: refine
}

export interface OutfitPiece {
  item_id: string;
  reason: string;
  alternates: string[];
}

export interface Outfit {
  id: string;
  name: string;
  vibe_summary: string;
  pieces: Partial<Record<Slot, OutfitPiece>>;
  total: Money;
  savings_vs_retail?: Money | null;
  within_budget: boolean;
}

// ───────────── Anjelo: 3D ─────────────

export type Vec3 = [number, number, number];

export interface Transform {
  position: Vec3;
  rotation: Vec3; // euler XYZ radians
  scale: Vec3;
}

export interface Asset3D {
  item_id: string;
  status: AssetStatus;
  tier: AssetTier;
  template_id?: string | null;
  glb_url?: string | null;
  voxel_glb_url?: string | null;
  thumbnail_url?: string | null;
  fit: Transform;
  follows_body_morphs: boolean;
  gen_seconds?: number | null;
  error?: string | null;
  created_at: string;
}

export interface GenJob {
  item_id: string;
  image_url: string;
  category: Category;
  tier: AssetTier;
  resolution: number; // 512 | 1024
}

// ───────────── Anjelo: avatar ─────────────

/** Sliders 0..1, 0.5 = base mesh. Keys match GLB morph target names. */
export interface BodyProfile {
  base: BodyBase;
  height: number;
  weight: number;
  muscle: number;
  shoulders: number;
  chest: number;
  waist: number;
  hips: number;
  leg_length: number;
  skin_tone: string;
}

export const BODY_SLIDERS = [
  "height", "weight", "muscle", "shoulders", "chest", "waist", "hips", "leg_length",
] as const satisfies readonly (keyof BodyProfile)[];

export const DEFAULT_BODY: BodyProfile = {
  base: "masc",
  height: 0.5, weight: 0.5, muscle: 0.5, shoulders: 0.5,
  chest: 0.5, waist: 0.5, hips: 0.5, leg_length: 0.5,
  skin_tone: "#c68e6a",
};

// ───────────── API envelopes ─────────────

export interface OutfitResponse {
  query: StyleQuery;
  outfits: Outfit[];
  items: Record<string, Item>;
  took_ms: number;
}

export interface ItemsResponse {
  items: Item[];
  total: number;
}

export interface ApiError {
  error: string;
  detail?: string | null;
}

// ───────────── helpers ─────────────

export const formatMoney = (m: Money) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: m.currency }).format(m.cents / 100);

/** Render order on avatar: inner layers first. */
export const SLOT_LAYER_ORDER: Slot[] = ["bottom", "top", "onepiece", "outer", "shoes", "accessory"];
