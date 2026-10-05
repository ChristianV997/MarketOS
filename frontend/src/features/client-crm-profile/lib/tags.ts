import { containsIgnoreCase, dedupeCaseInsensitive, splitTags } from "./text.ts";
import { validateTag } from "./validateProfile.ts";

export interface PreparedTags {
  /** Tags safe to add, in typed order, de-duplicated against the list. */
  accepted: string[];
  /** Already in the list (case-insensitive); reported, not added twice. */
  duplicates: string[];
  /** First problem found, or null. When set, nothing is accepted (all or nothing). */
  error: string | null;
}

/**
 * Turns one chip-input submission ("a, b\nc") into tags to add. All-or-nothing:
 * if any piece is invalid the whole entry is kept in the box with an error, so
 * the person can fix it instead of losing part of what they typed.
 */
export function prepareTags(input: string, existing: readonly string[], label: string, max: number): PreparedTags {
  const pieces = dedupeCaseInsensitive(splitTags(input));
  if (pieces.length === 0) return { accepted: [], duplicates: [], error: `Type a ${label.toLowerCase()} first.` };

  for (const piece of pieces) {
    const problem = validateTag(piece, label);
    if (problem) return { accepted: [], duplicates: [], error: problem };
  }

  const duplicates = pieces.filter((piece) => containsIgnoreCase(existing, piece));
  const accepted = pieces.filter((piece) => !containsIgnoreCase(existing, piece));
  if (existing.length + accepted.length > max) {
    return { accepted: [], duplicates, error: `You can add up to ${max} entries. Remove one first.` };
  }
  return { accepted, duplicates, error: null };
}
