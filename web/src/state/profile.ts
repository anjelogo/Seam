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
  bottomSize: "W32",
  body: { shoulders: 50, chest: 50, waist: 50, hips: 50, legs: 50 },
};

export type ProfilePatch = Partial<Omit<Profile, "body">> & { body?: Partial<Profile["body"]> };

const withPatch = (profile: Profile, { body, ...rest }: ProfilePatch): Profile => ({
  ...profile,
  ...rest,
  body: { ...profile.body, ...body },
});

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
      patch: (partial) => set(({ profile }) => ({ profile: withPatch(profile ?? DEFAULT_PROFILE, partial) })),
      bodyProfile: () => profileToBody(get().profile ?? DEFAULT_PROFILE),
      setDragging: (dragging) => set({ dragging }),
    }),
    {
      name: "seam.profile",
      storage: safeStorage,
      partialize: ({ profile }) => ({ profile }),
      // profiles saved by older versions lack newer fields
      merge: (persisted, current) => {
        const { profile } = { ...current, ...(persisted as { profile?: ProfilePatch | null }) };
        return { ...current, profile: profile && withPatch(DEFAULT_PROFILE, profile) };
      },
    },
  ),
);

export function useBodyProfile(): BodyProfile {
  const profile = useProfile((s) => s.profile);
  return useMemo(() => profileToBody(profile ?? DEFAULT_PROFILE), [profile]);
}
