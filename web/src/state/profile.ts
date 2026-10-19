import type { BodyProfile } from "@shared/types";
import { useMemo } from "react";
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { getProfile, putProfile } from "../lib/api";
import type { RequestError } from "../lib/api";
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

const SYNC_MS = 800;
let synced: Profile | null = null;
let syncTimer: number | undefined;

function flush() {
  const { profile, dragging } = useProfile.getState();
  if (!profile || dragging || profile === synced) return;
  synced = profile;
  putProfile(profile).catch(() => {
    if (synced === profile) synced = null;
  });
}

useProfile.subscribe((s, prev) => {
  if (s.profile === prev.profile && s.dragging === prev.dragging) return;
  window.clearTimeout(syncTimer);
  syncTimer = window.setTimeout(flush, SYNC_MS);
});

export async function fetchProfile(): Promise<boolean> {
  try {
    const { body } = await getProfile();
    synced = withPatch(DEFAULT_PROFILE, body);
    useProfile.getState().setProfile(synced);
    return true;
  } catch (err) {
    if ((err as RequestError)?.status !== 404) return useProfile.getState().profile !== null;
    clearProfile();
    return false;
  }
}

export function clearProfile() {
  window.clearTimeout(syncTimer);
  synced = null;
  useProfile.setState({ profile: null, dragging: false });
}

export function useBodyProfile(): BodyProfile {
  const profile = useProfile((s) => s.profile);
  return useMemo(() => profileToBody(profile ?? DEFAULT_PROFILE), [profile]);
}
