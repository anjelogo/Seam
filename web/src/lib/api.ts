import type {
  ApiError,
  Asset3D,
  Category,
  GenJob,
  Item,
  ItemsResponse,
  OutfitResponse,
  Slot,
  StyleQuery,
} from "@shared/types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = await res.json();
  if (!res.ok) throw body as ApiError;
  return body as T;
}

const post = <T>(url: string, body: unknown) =>
  request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export const postOutfits = (query: StyleQuery) => post<OutfitResponse>("/api/outfits", query);

export function getItems(
  params: { slot?: Slot; category?: Category; q?: string; max_cents?: number; limit?: number; offset?: number } = {},
) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined) qs.set(k, String(v));
  return request<ItemsResponse>(`/api/items?${qs}`);
}

export const getItem = (id: string) => request<Item>(`/api/items/${encodeURIComponent(id)}`);

export const postGenJob = (job: GenJob) => post<Asset3D>("/gen3d/jobs", job);

export const getGenJob = (itemId: string) => request<Asset3D>(`/gen3d/jobs/${encodeURIComponent(itemId)}`);

export async function pollGenJob(itemId: string, onUpdate: (asset: Asset3D) => void): Promise<Asset3D> {
  for (;;) {
    const asset = await getGenJob(itemId);
    onUpdate(asset);
    if (asset.status === "ready" || asset.status === "failed") return asset;
    await new Promise((resolve) => setTimeout(resolve, 2000));
  }
}
