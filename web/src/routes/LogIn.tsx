import { useState } from "react";
import { UnderlineField } from "../components/ui";
import { useProfile, useSession } from "../state";
import { AuthFrame } from "./auth/AuthFrame";
import { useAuthForm } from "./auth/useAuthForm";

export default function LogIn() {
  const login = useSession((s) => s.login);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const form = useAuthForm(async () => {
    await login(email, password);
    return useProfile.getState().profile ? "/avatar" : "/onboarding";
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
