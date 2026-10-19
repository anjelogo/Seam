import { useState } from "react";
import { useLocation } from "react-router-dom";
import { UnderlineField } from "../components/ui";
import { useSession } from "../state";
import { fetchProfile } from "../state/profile";
import { AuthFrame } from "./auth/AuthFrame";
import { useAuthForm } from "./auth/useAuthForm";

export default function LogIn() {
  const login = useSession((s) => s.login);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const from = (useLocation().state as { from?: string } | null)?.from;
  const form = useAuthForm(async () => {
    await login(email, password);
    return (await fetchProfile()) ? (from ?? "/avatar") : "/onboarding";
  });
  const ready = email.trim() !== "" && password.trim() !== "";

  return (
    <AuthFrame
      title="welcome back."
      action="log in"
      ready={ready}
      form={form}
      link={{ to: "/signup", label: "make an account" }}
    >
      <UnderlineField
        label="email"
        name="email"
        type="email"
        autoComplete="email"
        value={email}
        onChange={form.edit(setEmail)}
        {...form.tip("email")}
      />
      <UnderlineField
        label="password"
        name="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={form.edit(setPassword)}
        {...form.tip("password")}
      />
    </AuthFrame>
  );
}
