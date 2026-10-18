import { useState } from "react";
import { UnderlineField } from "../components/ui";
import { useSession } from "../state";
import { AuthFrame } from "./auth/AuthFrame";
import { useAuthForm } from "./auth/useAuthForm";

export default function SignUp() {
  const signup = useSession((s) => s.signup);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const form = useAuthForm(async () => {
    await signup(name, email, password);
    return "/onboarding";
  });
  const ready = [name, email, password].every((value) => value.trim() !== "");

  return (
    <AuthFrame
      title="make an account."
      action="continue"
      ready={ready}
      form={form}
      link={{ to: "/login", label: "i have an account" }}
    >
      <UnderlineField
        label="name"
        name="name"
        autoComplete="name"
        value={name}
        onChange={form.edit(setName)}
        {...form.tip("name")}
      />
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
        autoComplete="new-password"
        tipLabel="about password"
        value={password}
        onChange={form.edit(setPassword)}
        {...form.tip("password", "8 or more characters.")}
      />
    </AuthFrame>
  );
}
