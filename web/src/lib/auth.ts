export type User = { name?: string; email: string };

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

// TODO(anjelo): swap in real auth endpoint
export async function login(email: string, password: string): Promise<User> {
  const user: User = { email: required(email, "email") };
  required(password, "password");
  return user;
}

export async function signup(name: string, email: string, password: string): Promise<User> {
  const user: User = { name: required(name, "name"), email: required(email, "email") };
  required(password, "password");
  return user;
}
