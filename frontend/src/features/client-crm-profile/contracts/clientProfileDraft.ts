/**
 * Client CRM profile: the form's draft and the local "payload" it hands to a
 * persistence function.
 *
 * This is the FORM model, not the wire contract. The server's contract is
 * `api/routes/client_profile.py` (`/api/organization/client-profile`): it stores
 * only company name, business type, segments, target markets, offering NAMES and
 * social handles (always reported `not_connected`). `lib/serverProfile.ts` and
 * `lib/toServerBody.ts` map between the two; everything else in this file
 * (categories, offering details, social links and notes) is kept in the browser
 * tab only and is never sent. Nothing here is verified or connected.
 *
 * Identity: this contract deliberately has NO workspace/tenant/client id field.
 * Who the profile belongs to is decided by the server from the verified bearer
 * token, never from a value the user can type or select.
 */

export const CLIENT_PROFILE_DRAFT_SCHEMA_VERSION = "client-profile-draft-v0";

export const BUSINESS_TYPES = ["service_b2c", "service_b2b", "product", "other"] as const;
export type BusinessType = (typeof BUSINESS_TYPES)[number];

export const SERVICE_DELIVERY_MODES = ["remote", "on_site", "hybrid"] as const;
export type ServiceDelivery = (typeof SERVICE_DELIVERY_MODES)[number];

export const PRODUCT_AVAILABILITY = ["in_stock", "made_to_order", "dropship", "preorder", "unknown"] as const;
export type ProductAvailability = (typeof PRODUCT_AVAILABILITY)[number];

export const SOCIAL_PLATFORMS = ["instagram", "tiktok", "facebook", "x", "linkedin", "youtube", "pinterest", "threads", "other"] as const;
export type SocialPlatform = (typeof SOCIAL_PLATFORMS)[number];

export const LIMITS = {
  companyNameMin: 2,
  companyNameMax: 120,
  tagMin: 2,
  tagMax: 60,
  maxCategories: 10,
  maxSegments: 10,
  maxTargetMarkets: 20,
  /** The server accepts at most 25 entries per list. */
  maxOfferings: 25,
  offeringNameMax: 120,
  offeringDescriptionMax: 300,
  skuMax: 64,
  quantityMax: 1_000_000,
  maxSocialAccounts: 20,
  /** What the service itself accepts per list; the form limits above are stricter for segments, markets and social accounts. */
  serverListMax: 25,
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
  other: {
    label: "Other business model",
    description: "None of the above fits. You can still describe what you offer.",
    offeringNoun: "service",
    segmentsLabel: "Customer segments",
    segmentsHint: "Groups of people or companies you serve.",
    categoriesHint: "What kind of business this is.",
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
    /** Service businesses only, and only when chosen. Never sent to the profile service. */
    delivery?: ServiceDelivery;
    /** Product businesses only, and only when chosen. Never sent to the profile service. */
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
  "content_rejected",
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
