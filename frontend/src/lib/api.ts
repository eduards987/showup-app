// Minimal API client with Bearer token support.
// The in-memory token is kept in sync by AuthProvider (see src/lib/auth.tsx).

const BASE = process.env.EXPO_PUBLIC_BACKEND_URL ?? "";

let inMemoryToken: string | null = null;

export function setAuthToken(token: string | null) {
  inMemoryToken = token;
}

export function getAuthToken(): string | null {
  return inMemoryToken;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T = unknown>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string> | undefined),
  };
  if (inMemoryToken) headers.Authorization = `Bearer ${inMemoryToken}`;

  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  const text = await res.text();
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      // Corpo não-JSON (página de erro de proxy/gateway em vez da API) — não
      // deixa o JSON.parse estourar uma exceção crua pro chamador; ele só
      // sabe lidar com ApiError.
      data = null;
    }
  }
  if (!res.ok) {
    throw new ApiError(res.status, (data && data.detail) || text || res.statusText);
  }
  return data as T;
}
