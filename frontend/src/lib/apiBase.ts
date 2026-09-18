/** Shared API base URL resolution for frontend HTTP clients. */

export function resolveApiBaseUrl(): string {
  const base =
    (import.meta.env.VITE_API_BASE_URL as string | undefined)
    ?? (import.meta.env.VITE_API_URL as string | undefined)
    ?? "";
  return base.replace(/\/$/, "");
}

export function joinApiPath(baseUrl: string, path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}
