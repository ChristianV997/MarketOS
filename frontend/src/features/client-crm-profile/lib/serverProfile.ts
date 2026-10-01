import {
  BUSINESS_TYPES,
  CLIENT_PROFILE_DRAFT_SCHEMA_VERSION,
  LIMITS,
  PRODUCT_AVAILABILITY,
  SERVICE_DELIVERY_MODES,
  SOCIAL_PLATFORMS,
  type OfferingDraft,
  type ProfileDraft,
  type SocialAccountDraft,
} from "../contracts/clientProfileDraft.ts";

type Rec = Record<string, unknown>;
const isRecord = (value: unknown): value is Rec => typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const stringOrNull = (value: unknown): string | null | undefined => (value === null ? null : isString(value) ? value : undefined);
const oneOf = <T extends string>(list: readonly T[], value: unknown): value is T => isString(value) && (list as readonly string[]).includes(value);

function stringList(value: unknown, max: number): string[] | null {
  if (!Array.isArray(value) || value.length > max || !value.every(isString)) return null;
  return [...value];
}

/**
 * Server response -> form draft, or null when the body is not a valid profile
 * (the caller reports malformed_response). Strict: wrong schema version, a type
 * outside the contract, an over-limit list, or a social account that claims to
 * be anything but `not_connected` is refused, never repaired. Unknown extra
 * fields (including any tenant or workspace identifier) are ignored and never
 * copied into state.
 */
export function parseServerProfile(value: unknown): ProfileDraft | null {
  if (!isRecord(value) || value.schema_version !== CLIENT_PROFILE_DRAFT_SCHEMA_VERSION) return null;
  if (!isString(value.company_name) || !oneOf(BUSINESS_TYPES, value.business_type)) return null;
  const categories = stringList(value.categories, LIMITS.maxCategories);
  const segments = stringList(value.segments, LIMITS.maxSegments);
  const targetMarkets = stringList(value.target_markets, LIMITS.maxTargetMarkets);
  if (!categories || !segments || !targetMarkets) return null;
  if (!Array.isArray(value.offerings) || value.offerings.length > LIMITS.maxOfferings) return null;
  if (!Array.isArray(value.social_accounts) || value.social_accounts.length > LIMITS.maxSocialAccounts) return null;

  const offerings: OfferingDraft[] = [];
  for (const [index, raw] of value.offerings.entries()) {
    if (!isRecord(raw) || !isString(raw.name)) return null;
    const description = stringOrNull(raw.description ?? null);
    if (description === undefined) return null;
    const draft: OfferingDraft = {
      key: `offering-loaded-${index}`, name: raw.name, description: description ?? "",
      delivery: "", availability: "", sku: "", quantity: "",
    };
    if (value.business_type === "product") {
      if (!oneOf(PRODUCT_AVAILABILITY, raw.availability)) return null;
      const sku = stringOrNull(raw.sku ?? null);
      const quantity = raw.quantity ?? null;
      if (sku === undefined) return null;
      if (quantity !== null && !(typeof quantity === "number" && Number.isInteger(quantity) && quantity >= 0 && quantity <= LIMITS.quantityMax)) return null;
      draft.availability = raw.availability;
      draft.sku = sku ?? "";
      draft.quantity = quantity === null ? "" : String(quantity);
    } else {
      if (!oneOf(SERVICE_DELIVERY_MODES, raw.delivery)) return null;
      draft.delivery = raw.delivery;
    }
    offerings.push(draft);
  }

  const socialAccounts: SocialAccountDraft[] = [];
  for (const [index, raw] of value.social_accounts.entries()) {
    if (!isRecord(raw) || !oneOf(SOCIAL_PLATFORMS, raw.platform) || raw.link_status !== "not_connected") return null;
    const handle = stringOrNull(raw.handle ?? null);
    const url = stringOrNull(raw.url ?? null);
    const notes = stringOrNull(raw.notes ?? null);
    if (handle === undefined || url === undefined || notes === undefined) return null;
    socialAccounts.push({ key: `social-loaded-${index}`, platform: raw.platform, handle: handle ?? "", url: url ?? "", notes: notes ?? "" });
  }

  return {
    companyName: value.company_name,
    businessType: value.business_type,
    categories,
    segments,
    targetMarkets,
    offerings,
    socialAccounts,
  };
}
