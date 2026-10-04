/**
 * Detects text that looks like a credential. The form must never accept
 * passwords, tokens, API keys or secret values, so anything shaped like one is
 * rejected with an inline error rather than stored or displayed back.
 *
 * Heuristic by design: it prefers a clear "remove that" message over silently
 * keeping a possible secret.
 */

const CREDENTIAL_PATTERNS: readonly RegExp[] = [
  /\bsk[-_](live|test|proj)?[-_]?[A-Za-z0-9]{16,}/i, // API secret keys
  /\bgh[pousr]_[A-Za-z0-9]{20,}/, // GitHub tokens
  /\bgithub_pat_[A-Za-z0-9_]{20,}/,
  /\bxox[abprs]-[A-Za-z0-9-]{10,}/, // Slack tokens
  /\bAKIA[0-9A-Z]{16}\b/, // AWS access key id
  /\bAIza[0-9A-Za-z_-]{30,}/, // Google API key
  /\bEA[A-Za-z]{1,3}[A-Za-z0-9]{40,}/, // Meta/Facebook access tokens
  /\bbearer\s+[A-Za-z0-9._~+/-]{10,}/i,
  /\b(pass(word|wd)?|pwd|secret|token|api[_ -]?key|access[_ -]?key|client[_ -]?secret|2fa|otp)\b\s*[:=]\s*\S+/i,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /\b[A-Za-z0-9_-]{32,}\b/, // long unbroken token-shaped run in a short free-text field
];

export function looksLikeSecret(value: string): boolean {
  return CREDENTIAL_PATTERNS.some((pattern) => pattern.test(value));
}

export const SECRET_MESSAGE =
  "This looks like a password, token or key. MarketOS never needs these here. Remove it, or reword it if it is an ordinary value.";

/** Query-string keys that must not appear in a profile link. */
const SECRET_QUERY_WORDS = new Set([
  "token", "secret", "password", "passwd", "pass", "pwd", "apikey", "key", "auth",
  "session", "sig", "signature", "code", "otp", "credential", "credentials",
]);

/** "access_token" -> ["access", "token"]; "keyword" stays whole so it is not a false positive. */
function isSecretQueryKey(key: string): boolean {
  return key
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .some((word) => SECRET_QUERY_WORDS.has(word));
}

export type UrlProblem =
  | "not_a_url"
  | "not_https"
  | "has_credentials"
  | "has_secret_query"
  | "too_long"
  | "no_host";

/** Structural checks shared by every social/profile link. Returns null when acceptable. */
export function findUrlProblem(raw: string, maxLength: number): { problem: UrlProblem; url: URL | null } | null {
  if (raw.length > maxLength) return { problem: "too_long", url: null };
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { problem: "not_a_url", url: null };
  }
  if (url.protocol !== "https:") return { problem: "not_https", url };
  if (url.username || url.password) return { problem: "has_credentials", url };
  if (!url.hostname.includes(".")) return { problem: "no_host", url };
  for (const key of url.searchParams.keys()) {
    if (isSecretQueryKey(key)) return { problem: "has_secret_query", url };
  }
  if (looksLikeSecret(url.hash.replace(/^#/, "")) && url.hash.length > 1) return { problem: "has_secret_query", url };
  return null;
}
