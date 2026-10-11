/** Display helpers for untrusted ledger strings. Never treat text as HTML. */

const CONTROL = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g;
const ANGLE = /[<>]/g;

/** Strip control chars and angle brackets so React text nodes stay plain. */
export function safeDisplayText(value: unknown, limit = 400): string {
  const raw = String(value ?? "");
  const cleaned = raw.replace(CONTROL, "").replace(ANGLE, "").replace(/\s+/g, " ").trim();
  if (cleaned.length <= limit) return cleaned;
  return `${cleaned.slice(0, Math.max(0, limit - 1))}…`;
}

export function humanizeToken(value: unknown): string {
  const text = safeDisplayText(value, 120);
  if (!text) return "unavailable";
  return text.replace(/_/g, " ");
}
