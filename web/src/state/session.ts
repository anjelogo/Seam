import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as auth from "../lib/auth";
import type { User } from "../lib/auth";
import { safeStorage } from "./storage";

type SessionState = {
  user: User | null;
  login(email: string, password: string): Promise<User>;
  signup(name: string, email: string, password: string): Promise<User>;
  logout(): void;
};

export const useSession = create<SessionState>()(
  persist(
    (set) => ({
      user: null,
      login: async (email, password) => {
        const user = await auth.login(email, password);
        set({ user });
        return user;
      },
      signup: async (name, email, password) => {
        const user = await auth.signup(name, email, password);
        set({ user });
        return user;
      },
      logout: () => set({ user: null }),
    }),
    { name: "seam.session", storage: safeStorage, partialize: ({ user }) => ({ user }) },
  ),
);
