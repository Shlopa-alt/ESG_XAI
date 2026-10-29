export type Role = "reader" | "researcher" | "reviewer" | "owner";

export interface User {
  id: number;
  login: string;
  full_name: string;
  email: string;
  role: Role;
  nda_access: boolean;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as { detail?: string } | null;
    throw new ApiError(res.status, body?.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Текущий пользователь; null, если вход не выполнен. */
export async function fetchMe(): Promise<User | null> {
  try {
    return await request<User>("/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export function login(loginName: string, password: string): Promise<User> {
  return request<User>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ login: loginName, password }),
  });
}

export async function logout(): Promise<void> {
  await request<null>("/auth/logout", { method: "POST" });
}
