import type { BodyProfile } from "@shared/types";
import { useMemo } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { profileToBody } from "../lib/viewmodel";
import type { Profile } from "../lib/viewmodel";
import { safeStorage } from "./storage";

export const DEFAULT_PROFILE: Profile = {
  heightCm: 170,
  weight: 150,
  weightUnit: "lb",
  base: "masc",
  skinTone: "#B9805A",
  topSize: "M",
  body: { shoulders: 50, chest: 50, waist: 50, hips: 50, legs: 50 },
};

export type ProfilePatch = Partial<Omit<Profile, "body">> & { body?: Partial<Profile["body"]> };

type ProfileState = {
  profile: Profile | null;
  dragging: boolean;
  setProfile(p: Profile): void;
  patch(partial: ProfilePatch): void;
  bodyProfile(): BodyProfile;
  setDragging(dragging: boolean): void;
};

export const useProfile = create<ProfileState>()(
  persist(
    (set, get) => ({
      profile: null,
      dragging: false,
      setProfile: (profile) => set({ profile }),
      patch: ({ body, ...rest }) =>
        set(({ profile }) => {
          const current = profile ?? DEFAULT_PROFILE;
          return { profile: { ...current, ...rest, body: { ...current.body, ...body } } };
        }),
      bodyProfile: () => profileToBody(get().profile ?? DEFAULT_PROFILE),
      setDragging: (dragging) => set({ dragging }),
    }),
    { name: "seam.profile", storage: safeStorage, partialize: ({ profile }) => ({ profile }) },
  ),
);

export function useBodyProfile(): BodyProfile {
  const profile = useProfile((s) => s.profile);
  return useMemo(() => profileToBody(profile ?? DEFAULT_PROFILE), [profile]);
}
