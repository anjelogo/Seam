import type { Garment } from "@shared/types";
import { create } from "zustand";
import { getGarments } from "../lib/api";
import { useLook } from "./look";

type InventoryState = {
  query: string;
  results: Garment[];
  loading: boolean;
  error: string | null;
  search(q: string, immediate?: boolean): void;
};

let timer = 0;
let latest = 0;

export const useInventory = create<InventoryState>()((set) => ({
  query: "",
  results: [],
  loading: false,
  error: null,
  search: (q, immediate = false) => {
    const seq = ++latest;
    window.clearTimeout(timer);
    set({ query: q });
    const run = async () => {
      set({ loading: true });
      try {
        const res = await getGarments({ q: q.trim() || undefined, limit: 100 });
        if (seq !== latest) return;
        set({ results: res.garments, loading: false, error: null });
        useLook.getState().addItems(res.garments);
      } catch {
        if (seq === latest) set({ loading: false, error: "search isn't working right now." });
      }
    };
    if (immediate) void run();
    else timer = window.setTimeout(run, 300);
  },
}));
