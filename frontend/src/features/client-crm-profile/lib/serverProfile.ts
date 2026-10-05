import {
  BUSINESS_TYPES,
  LIMITS,
  SOCIAL_PLATFORMS,
  type OfferingDraft,
  type ProfileDraft,
  type SocialAccountDraft,
} from "../contracts/clientProfileDraft.ts";

type Rec = Record<string, unknown>;
const isRecord = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const oneOf = <T extends string>(list: readonly T[], value: unknown): value is T => isString(value) && (list as readonly string[]).includes(value);

function stringList(value: unknown, max: number): string[] | null {
  if (!Array.isArray(value) || value.length > max || !value.every(isString)) return null;
  return [...value];
}

/**
 * Service response -> form draft, or null when the body is not a valid profile
 * (the caller reports malformed_response). The service returns only company name,
 * business type, segments, target markets, offering names and social handles;
 * every other form field starts empty and is the person's to fill in.
 *
 * Strict: a type outside the contract, a list over the service's own limit (25; the form's stricter limits are flagged by validation, not by refusing to load), or a social account
 * that claims to be anything but `not_connected` is refused, never repaired.
 * Unknown extra fields (including any tenant or workspace identifier) are ignored
 * and never copied into state.
 */
export function parseServerProfile(value: unknown): ProfileDraft | null {
  if (!isRecord(value)) return null;
  if (!isString(value.company_name) || !oneOf(BUSINESS_TYPES, value.business_type)) return null;
  const segments = stringList(value.segments, LIMITS.serverListMax);
  const targetMarkets = stringList(value.target_markets, LIMITS.serverListMax);
  const offeringNames = stringList(value.offerings, LIMITS.serverListMax);
  if (!segments || !targetMarkets || !offeringNames) return null;
  if (!Array.isArray(value.social_accounts) || value.social_accounts.length > LIMITS.serverListMax) return null;

  const offerings: OfferingDraft[] = offeringNames.map((name, index) => ({
    key: `offering-loaded-${index}`, name, description: "", delivery: "", availability: "", sku: "", quantity: "",
  }));

  const socialAccounts: SocialAccountDraft[] = [];
  for (const [index, raw] of value.social_accounts.entries()) {
    if (!isRecord(raw) || !oneOf(SOCIAL_PLATFORMS, raw.platform) || !isString(raw.handle)) return null;
    if (raw.connection_state !== "not_connected") return null;
    socialAccounts.push({ key: `social-loaded-${index}`, platform: raw.platform, handle: raw.handle.replace(/^@/, ""), url: "", notes: "" });
  }

  return {
    companyName: value.company_name,
    businessType: value.business_type,
    categories: [],
    segments,
    targetMarkets,
    offerings,
    socialAccounts,
  };
}
