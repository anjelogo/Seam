import { useRef, useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { AuthError } from "../../lib/auth";

type Field = AuthError["field"];

export type AuthForm = ReturnType<typeof useAuthForm>;

export function useAuthForm(run: () => Promise<string>) {
  const navigate = useNavigate();
  const busy = useRef(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<AuthError | null>(null);
  const [shake, setShake] = useState(0);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError(null);
    try {
      navigate(await run());
    } catch (err) {
      busy.current = false;
      setPending(false);
      if (!(err instanceof AuthError)) throw err;
      setError(err);
      setShake((n) => n + 1);
      form.querySelector<HTMLInputElement>(`[name="${err.field}"]`)?.focus();
    }
  };

  const edit = (set: (value: string) => void) => (event: ChangeEvent<HTMLInputElement>) => {
    set(event.target.value);
    setError(null);
  };

  const tip = (field: Field, rule?: string) => {
    const message = error?.field === field ? error.message : undefined;
    const failed = message !== undefined;
    return { tip: message ?? rule, tipOpen: failed, "aria-invalid": failed || undefined };
  };

  return { pending, error, shake, onSubmit, edit, tip };
}
