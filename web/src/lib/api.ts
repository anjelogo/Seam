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

import type { User } from "./auth";
import type { Look, Profile } from "./viewmodel";

export type RequestError = ApiError & { status: number; field?: string };

let onUnauthorized = () => {};

export const handleUnauthorized = (fn: () => void) => {
  onUnauthorized = fn;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  if (res.status === 401) onUnauthorized();
  if (!res.ok) throw { error: res.statusText, ...(body as ApiError | null), status: res.status } as RequestError;
  return body as T;
}

const send = <T>(method: string, url: string, body?: unknown) =>
  request<T>(url, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

const post = <T>(url: string, body?: unknown) => send<T>("POST", url, body);

export const postSignup = (name: string, email: string, password: string) =>
  post<User>("/api/auth/signup", { name, email, password });

export const postLogin = (email: string, password: string) => post<User>("/api/auth/login", { email, password });

export const postLogout = () => post<null>("/api/auth/logout");

export const getMe = () => request<User>("/api/auth/me");

export const getProfile = () => request<{ body: Profile }>("/api/me/profile");

export const putProfile = (body: Profile) => send<{ body: Profile }>("PUT", "/api/me/profile", { body });

export const getLooks = () => request<(Look & { id: string })[]>("/api/me/looks");

export const postLook = (look: Look) => post<Look & { id: string }>("/api/me/looks", look);

export const getAdminStats = () => request<{ items: number; tagged: number; active: number }>("/api/admin/stats");

export async function exportItems(): Promise<{ blob: Blob; name: string }> {
  const res = await fetch("/api/admin/export/items");
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as ApiError | null;
    throw { error: res.statusText, ...body, status: res.status } as RequestError;
  }
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "items.jsonl";
  return { blob: await res.blob(), name };
}

export const postOutfits =(query: StyleQuery) => post<OutfitResponse>("/api/outfits", query);

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
