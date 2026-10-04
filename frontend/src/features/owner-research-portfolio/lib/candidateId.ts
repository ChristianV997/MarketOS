import { MAX_CANDIDATE_ID_LENGTH } from "../contracts/ownerResearch";

// eslint-disable-next-line no-control-regex
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/;

/**
 * Candidate identity is an exact, opaque backend id. It is never derived from a
 * title, SKU, supplier display name or position, and never case-folded or
 * trimmed: an id that would need normalising is treated as malformed so an
 * ambiguous entry can under-count but can never double-count.
 */
export function isStableCandidateId(value: unknown): value is string {
  return (
    typeof value === "string"
    && value.length > 0
    && value.length <= MAX_CANDIDATE_ID_LENGTH
    && value === value.trim()
    && !CONTROL_CHARS.test(value)
  );
}
