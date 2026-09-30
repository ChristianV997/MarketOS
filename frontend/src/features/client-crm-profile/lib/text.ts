/** Small text helpers shared by validation, the reducer and the payload builder. */

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/;

/** Trim and collapse internal whitespace. */
export function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function hasControlChars(value: string): boolean {
  return CONTROL_CHARS.test(value);
}

/** Split pasted "a, b\nc" input into candidate tags. */
export function splitTags(input: string): string[] {
  return input
    .split(/[,\n;]/)
    .map(normalizeText)
    .filter((part) => part.length > 0);
}

/** Case-insensitive de-duplication that keeps the first spelling. */
export function dedupeCaseInsensitive(values: readonly string[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    const key = value.toLocaleLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(value);
  }
  return out;
}

export function containsIgnoreCase(list: readonly string[], value: string): boolean {
  const key = value.toLocaleLowerCase();
  return list.some((item) => item.toLocaleLowerCase() === key);
}

/** Shown wherever a value was not provided, so a blank is never mistaken for a real value. */
export const NOT_PROVIDED = "Not provided";
