/**
 * Client CRM profile: draft contract.
 *
 * STATUS: frontend-proposed, NOT backed by any API. Verified on main: there is no
 * client-profile endpoint, no authenticated identity and no tenant enforcement
 * (api/onboarding.py is an in-memory, unauthenticated store-setup wizard keyed by
 * a client-supplied session id; ClientWorkspace has no profile fields and derives
 * workspace_id from its name). The backend owns the final schema; nothing here
 * should be treated as canonical.
 *
 * Identity: this contract deliberately has NO workspace/tenant/client id field.
 * Who the profile belongs to must come from the authenticated session on the
 * server, never from a value the user can type or select.
 */

export const CLIENT_PROFILE_DRAFT_SCHEMA_VERSION = "client-profile-draft-v0";

export const BUSINESS_TYPES = ["service_b2c", "service_b2b", "product"] as const;
export type BusinessType = (typeof BUSINESS_TYPES)[number];

export const SERVICE_DELIVERY_MODES = ["remote", "on_site", "hybrid"] as const;
export type ServiceDelivery = (typeof SERVICE_DELIVERY_MODES)[number];

export const PRODUCT_AVAILABILITY = ["in_stock", "made_to_order", "dropship", "preorder", "unknown"] as const;
export type ProductAvailability = (typeof PRODUCT_AVAILABILITY)[number];

export const SOCIAL_PLATFORMS = ["instagram", "tiktok", "facebook", "x", "linkedin", "youtube", "pinterest", "other"] as const;
export type SocialPlatform = (typeof SOCIAL_PLATFORMS)[number];

export const LIMITS = {
  companyNameMin: 2,
  companyNameMax: 120,
  tagMin: 2,
  tagMax: 60,
  maxCategories: 10,
  maxSegments: 10,
  maxTargetMarkets: 20,
  maxOfferings: 50,
  offeringNameMax: 120,
  offeringDescriptionMax: 300,
  skuMax: 64,
  quantityMax: 1_000_000,
  maxSocialAccounts: 20,
  handleMax: 64,
  urlMax: 300,
  notesMax: 200,
} as const;

export interface BusinessTypeMeta {
  label: string;
  description: string;
  /** Noun used for one offering ("service" | "product"). */
  offeringNoun: "service" | "product";
  segmentsLabel: string;
  segmentsHint: string;
  categoriesHint: string;
  /** Only product businesses declare availability / SKU / quantity. */
  tracksInventory: boolean;
}

export const BUSINESS_TYPE_META: Record<BusinessType, BusinessTypeMeta> = {
  service_b2c: {
    label: "Service for consumers (B2C)",
    description: "You sell a service directly to individual people.",
    offeringNoun: "service",
    segmentsLabel: "Customer segments",
    segmentsHint: "Groups of people you serve, for example \"new parents\" or \"first-time home buyers\".",
    categoriesHint: "What kind of service business this is, for example \"personal training\".",
    tracksInventory: false,
  },
  service_b2b: {
    label: "Service for businesses (B2B)",
    description: "You sell a service to other companies or organisations.",
    offeringNoun: "service",
    segmentsLabel: "Buyer segments",
    segmentsHint: "Kinds of companies or teams you serve, for example \"mid-market SaaS\" or \"regional retailers\".",
    categoriesHint: "What kind of service business this is, for example \"bookkeeping\".",
    tracksInventory: false,
  },
  product: {
    label: "Product business",
    description: "You sell physical or digital products, with or without stock.",
    offeringNoun: "product",
    segmentsLabel: "Customer segments",
    segmentsHint: "Groups of buyers you sell to, for example \"home baristas\" or \"gift shoppers\".",
    categoriesHint: "Product categories you sell, for example \"coffee equipment\".",
    tracksInventory: true,
  },
};

// ---------------------------------------------------------------------------
// Draft (what the form edits). Free text stays a string until validated.
// ---------------------------------------------------------------------------

export interface OfferingDraft {
  /** Stable client-side key for list rendering and focus; never sent. */
  key: string;
  name: string;
  description: string;
  /** Service businesses only. "" = not chosen yet. */
  delivery: ServiceDelivery | "";
  /** Product businesses only. "" = not chosen yet. */
  availability: ProductAvailability | "";
  sku: string;
  /** Kept as typed so an empty box is "not reported", never 0. */
  quantity: string;
}

export interface SocialAccountDraft {
  key: string;
  platform: SocialPlatform | "";
  handle: string;
  url: string;
  notes: string;
}

export interface ProfileDraft {
  companyName: string;
  businessType: BusinessType | null;
  categories: string[];
  segments: string[];
  targetMarkets: string[];
  offerings: OfferingDraft[];
  socialAccounts: SocialAccountDraft[];
}

// ---------------------------------------------------------------------------
// Payload handed to an (optional) persistence function.
// ---------------------------------------------------------------------------

export interface ClientProfileDraftPayload {
  schema_version: typeof CLIENT_PROFILE_DRAFT_SCHEMA_VERSION;
  company_name: string;
  business_type: BusinessType;
  categories: string[];
  segments: string[];
  target_markets: string[];
  offerings: Array<{
    name: string;
    description: string | null;
    /** Present for service businesses only. */
    delivery?: ServiceDelivery;
    /** Present for product businesses only. */
    availability?: ProductAvailability;
    sku?: string | null;
    /** Self-reported and unverified; null when not reported. */
    quantity?: number | null;
  }>;
  social_accounts: Array<{
    platform: SocialPlatform;
    handle: string | null;
    url: string | null;
    notes: string | null;
    /**
     * A typed handle or link is profile detail only. It is never verified and
     * never grants MarketOS access, so the only representable value is this one.
     */
    link_status: "not_connected";
  }>;
}

/** Persistence seam. Supplied by an authenticated integration; absent in demo mode. */
export type SaveClientProfile = (payload: ClientProfileDraftPayload) => Promise<void>;

/**
 * Why a profile request failed, as a short code. One code per failure the UI
 * words differently: 401, 403, 404, 409, 503, a 2xx body that is not a valid
 * profile, and a request that never got a response.
 */
export const PROFILE_ERROR_CODES = [
  "unauthenticated",
  "forbidden",
  "not_found",
  "conflict",
  "unavailable",
  "malformed_response",
  "network",
  "validation",
  "unknown",
] as const;
export type ProfileErrorCode = (typeof PROFILE_ERROR_CODES)[number];

/** A save failure the UI may show. Raw error text is never displayed. */
export class ProfileSaveError extends Error {
  readonly code: ProfileErrorCode;
  constructor(code: ProfileErrorCode) {
    super(code);
    this.name = "ProfileSaveError";
    this.code = code;
  }
}

export const STEP_IDS = ["company", "audience", "offerings", "social", "review"] as const;
export type StepId = (typeof STEP_IDS)[number];

export const STEP_META: Record<StepId, { title: string; short: string }> = {
  company: { title: "Company and business model", short: "Company" },
  audience: { title: "Categories, segments and target markets", short: "Audience" },
  offerings: { title: "Products, services and inventory", short: "Offerings" },
  social: { title: "Social accounts (details only)", short: "Social" },
  review: { title: "Review and confirm", short: "Review" },
};
