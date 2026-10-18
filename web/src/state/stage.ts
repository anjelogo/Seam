import { create } from "zustand";

type StageState = {
  yaw: number;
  setYaw(yaw: number): void;
  selected: string | null;
  select(id: string | null): void;
  checkoutOpen: boolean;
  setCheckoutOpen(open: boolean): void;
};

export const useStage = create<StageState>()((set) => ({
  yaw: 0,
  setYaw: (yaw) => set({ yaw }),
  selected: null,
  select: (selected) => set({ selected }),
  checkoutOpen: false,
  setCheckoutOpen: (checkoutOpen) => set({ checkoutOpen }),
}));
