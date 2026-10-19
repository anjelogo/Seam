import * as api from "./api";
import type { RequestError } from "./api";

export type User = { id: string; email: string; name: string };

type AuthField = "name" | "email" | "password";

export class AuthError extends Error {
  field: AuthField;

  constructor(message: string, field: AuthField) {
    super(message);
    this.name = "AuthError";
    this.field = field;
  }
}

function required(value: string, field: AuthField) {
  const trimmed = value.trim();
  if (!trimmed) throw new AuthError("fill this in.", field);
  return trimmed;
}

const FIELDS: AuthField[] = ["name", "email", "password"];

function toAuthError(err: unknown, fallback: AuthField): AuthError {
  const { status, detail, field } = (err ?? {}) as Partial<RequestError>;
  const known = FIELDS.find((f) => f === field);
  if (known && detail && status && [401, 409, 422, 429].includes(status)) return new AuthError(detail, known);
  return new AuthError("something went wrong. try again.", fallback);
}

export async function login(email: string, password: string): Promise<User> {
  const address = required(email, "email");
  required(password, "password");
  return api.postLogin(address, password).catch((err) => {
    throw toAuthError(err, "email");
  });
}

export async function signup(name: string, email: string, password: string): Promise<User> {
  const fullName = required(name, "name");
  const address = required(email, "email");
  required(password, "password");
  return api.postSignup(fullName, address, password).catch((err) => {
    throw toAuthError(err, "email");
  });
}

export const me = (): Promise<User | null> =>
  api.getMe().catch((err: Partial<RequestError>) => {
    if (err?.status === 401) return null;
    throw err;
  });

export const logout = () => api.postLogout();
