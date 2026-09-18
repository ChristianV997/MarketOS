/** Shared API base URL resolution for frontend HTTP clients (#213 authority). */

export function resolveApiBaseUrl(): string {
  const env = (import.meta as ImportMeta & { env?: Record<string, string | undefined> }).env ?? {};
  const base = env.VITE_API_BASE_URL ?? env.VITE_API_URL ?? "";
  return base.replace(/\/$/, "");
}

export function joinApiPath(baseUrl: string, path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}
