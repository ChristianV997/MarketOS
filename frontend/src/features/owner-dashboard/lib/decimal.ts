/**
 * Strict decimal handling for provider values.
 *
 * The provider serialises money and ratios as decimal *strings* ("945.0000",
 * "0E-8", "6E+1") and uses the strings "unknown" / null for missing values.
 * `Number("")` is 0 and `Number(null)` is 0, so missing values must never go
 * through bare Number(): parseDecimal returns null for anything that is not a
 * well-formed finite decimal, and callers render null as "Not available".
 */

const DECIMAL = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;

export function parseDecimal(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string") return null;
  const text = value.trim();
  if (!DECIMAL.test(text)) return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

export const NOT_AVAILABLE = "Not available";

export function formatMoney(numeric: number, currency: string | null): string {
  const code = currency && /^[A-Za-z]{3}$/.test(currency) ? currency.toUpperCase() : null;
  const digits = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric);
  return code ? `${code} ${digits}` : digits;
}

export function formatRatio(numeric: number, digits = 2): string {
  return new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(numeric);
}

export function formatPercent(fraction: number, digits = 1): string {
  return `${new Intl.NumberFormat("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(fraction * 100)}%`;
}
