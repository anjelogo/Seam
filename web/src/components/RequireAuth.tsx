import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useSession } from "../state";
import { TeeLoader } from "./brand";

export function RequireAuth({ children }: { children: ReactNode }) {
  const status = useSession((s) => s.status);
  const location = useLocation();
  if (status === "unknown") return <TeeLoader />;
  if (status === "anon") return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return children;
}
