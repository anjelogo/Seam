import { create } from "zustand";
import { handleUnauthorized } from "../lib/api";
import * as auth from "../lib/auth";
import type { User } from "../lib/auth";
import { clearSaved, fetchSaved } from "./look";
import { clearProfile, fetchProfile } from "./profile";

type Status = "unknown" | "authed" | "anon";

type SessionState = {
  user: User | null;
  status: Status;
  hydrate(): Promise<void>;
  login(email: string, password: string): Promise<User>;
  signup(name: string, email: string, password: string): Promise<User>;
  logout(): Promise<void>;
};

let hydrating: Promise<void> | null = null;

export const useSession = create<SessionState>()((set) => {
  const signedIn = (user: User) => {
    set({ user, status: "authed" });
    void fetchSaved();
    return user;
  };
  return {
    user: null,
    status: "unknown",
    hydrate: () =>
      (hydrating ??= auth
        .me()
        .then((user) => {
          if (!user) return set({ user: null, status: "anon" });
          signedIn(user);
          void fetchProfile();
        })
        .catch(() => set({ user: null, status: "anon" }))),
    login: async (email, password) => signedIn(await auth.login(email, password)),
    signup: async (name, email, password) => {
      const user = await auth.signup(name, email, password);
      clearProfile();
      return signedIn(user);
    },
    logout: async () => {
      await auth.logout().catch(() => {});
      clearProfile();
      clearSaved();
      set({ user: null, status: "anon" });
    },
  };
});

handleUnauthorized(() => useSession.setState({ user: null, status: "anon" }));
