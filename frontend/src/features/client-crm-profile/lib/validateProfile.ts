import {
  BUSINESS_TYPE_META,
  LIMITS,
  STEP_IDS,
  type BusinessType,
  type OfferingDraft,
  type ProfileDraft,
  type SocialAccountDraft,
  type SocialPlatform,
  type StepId,
} from "../contracts/clientProfileDraft.ts";
import { findUrlProblem, looksLikeSecret, SECRET_MESSAGE } from "./secretShape.ts";
import { hasControlChars, normalizeText } from "./text.ts";

export type FieldErrorCode = "required" | "invalid" | "too_short" | "too_long" | "duplicate" | "secret" | "too_many";

export interface FieldError {
  /** Dotted path, e.g. "offerings.0.name". Also the anchor for the error summary link. */
  path: string;
  step: StepId;
  code: FieldErrorCode;
  message: string;
}

export interface ProfileValidation {
  errors: FieldError[];
  byStep: Record<StepId, FieldError[]>;
  /** True only when every required item is present and every value is valid. */
  complete: boolean;
}

/** DOM id for a field path. Kept here so error links and inputs cannot drift apart. */
export function fieldId(path: string): string {
  return `cp-${path.replace(/\./g, "-")}`;
}

/** Same character set the profile service accepts for a handle (no dash). */
const HANDLE = /^[A-Za-z0-9._]{1,64}$/;
const SKU = /^[A-Za-z0-9._\-/ ]{1,64}$/;

const PLATFORM_HOSTS: Record<Exclude<SocialPlatform, "other">, readonly string[]> = {
  threads: ["threads.net", "threads.com"],
  instagram: ["instagram.com"],
  tiktok: ["tiktok.com"],
  facebook: ["facebook.com", "fb.com"],
  x: ["x.com", "twitter.com"],
  linkedin: ["linkedin.com"],
  youtube: ["youtube.com", "youtu.be"],
  pinterest: ["pinterest.com"],
};

export const PLATFORM_LABEL: Record<SocialPlatform, string> = {
  instagram: "Instagram",
  tiktok: "TikTok",
  facebook: "Facebook",
  x: "X",
  linkedin: "LinkedIn",
  youtube: "YouTube",
  pinterest: "Pinterest",
  threads: "Threads",
  other: "Other",
};

export function stepOfPath(path: string): StepId {
  if (path === "companyName" || path === "businessType") return "company";
  if (path === "categories" || path === "segments" || path === "targetMarkets") return "audience";
  if (path.startsWith("offerings")) return "offerings";
  if (path.startsWith("socialAccounts")) return "social";
  return "review";
}

/** Strip one leading "@" so "@shop" and "shop" are the same handle. */
export function normalizeHandle(value: string): string {
  return normalizeText(value).replace(/^@/, "");
}

/**
 * Message for one tag (category, segment or market) being added, or null when
 * acceptable. Shared by the chip input and the whole-profile validator.
 */
export function validateTag(value: string, label: string): string | null {
  const text = normalizeText(value);
  if (text.length < LIMITS.tagMin) return `${label} must be at least ${LIMITS.tagMin} characters.`;
  if (text.length > LIMITS.tagMax) return `${label} must be ${LIMITS.tagMax} characters or fewer.`;
  if (hasControlChars(text)) return `${label} contains characters that are not allowed.`;
  if (looksLikeSecret(text)) return SECRET_MESSAGE;
  return null;
}

function hostMatches(hostname: string, allowed: readonly string[]): boolean {
  const host = hostname.toLowerCase();
  return allowed.some((entry) => host === entry || host.endsWith(`.${entry}`));
}

/** Message for a profile link, or null when acceptable for the platform. */
export function validateProfileUrl(raw: string, platform: SocialPlatform | ""): string | null {
  const value = raw.trim();
  const found = findUrlProblem(value, LIMITS.urlMax);
  if (found) {
    switch (found.problem) {
      case "too_long": return `The link must be ${LIMITS.urlMax} characters or fewer.`;
      case "not_a_url": return "Enter a full link that starts with https://";
      case "not_https": return "Use a link that starts with https://";
      case "no_host": return "That link has no valid website address.";
      case "has_credentials": return "Remove the username or password from the link. MarketOS never needs them.";
      case "has_secret_query": return "This link carries a token, key or session value. Use the plain public profile link instead.";
    }
  }
  if (platform && platform !== "other") {
    const url = new URL(value);
    if (!hostMatches(url.hostname, PLATFORM_HOSTS[platform])) {
      return `This link does not look like a ${PLATFORM_LABEL[platform]} address.`;
    }
  }
  return null;
}

function tagListErrors(
  path: "categories" | "segments" | "targetMarkets",
  values: readonly string[],
  requiredMessage: string | null,
  max: number,
  label: string,
): FieldError[] {
  const step = stepOfPath(path);
  if (values.length === 0) return requiredMessage === null ? [] : [{ path, step, code: "required", message: requiredMessage }];
  const errors: FieldError[] = [];
  if (values.length > max) {
    errors.push({ path, step, code: "too_many", message: `Keep ${label} to ${max} entries or fewer.` });
  }
  for (const value of values) {
    const problem = validateTag(value, label);
    if (problem) {
      errors.push({ path, step, code: looksLikeSecret(value) ? "secret" : "invalid", message: `"${value}": ${problem}` });
    }
  }
  return errors;
}

function offeringErrors(offering: OfferingDraft, index: number, type: BusinessType | null): FieldError[] {
  const errors: FieldError[] = [];
  const base = `offerings.${index}`;
  const add = (field: string, code: FieldErrorCode, message: string) =>
    errors.push({ path: `${base}.${field}`, step: "offerings", code, message });
  const noun = type ? BUSINESS_TYPE_META[type].offeringNoun : "product or service";
  const n = index + 1;

  const name = normalizeText(offering.name);
  if (!name) add("name", "required", `Enter a name for ${noun} ${n}.`);
  else if (name.length > LIMITS.offeringNameMax) add("name", "too_long", `The name must be ${LIMITS.offeringNameMax} characters or fewer.`);
  else if (hasControlChars(name)) add("name", "invalid", "The name contains characters that are not allowed.");
  else if (looksLikeSecret(name)) add("name", "secret", SECRET_MESSAGE);

  const description = normalizeText(offering.description);
  if (description.length > LIMITS.offeringDescriptionMax) {
    add("description", "too_long", `The description must be ${LIMITS.offeringDescriptionMax} characters or fewer.`);
  } else if (description && hasControlChars(description)) {
    add("description", "invalid", "The description contains characters that are not allowed.");
  } else if (description && looksLikeSecret(description)) {
    add("description", "secret", SECRET_MESSAGE);
  }

  // Delivery and availability are not stored by the profile service, so they are optional.
  if (type && BUSINESS_TYPE_META[type].tracksInventory) {
    const sku = offering.sku.trim();
    if (sku && !SKU.test(sku)) add("sku", "invalid", `The SKU can use letters, numbers and . _ - / up to ${LIMITS.skuMax} characters.`);
    else if (sku && looksLikeSecret(sku)) add("sku", "secret", SECRET_MESSAGE);
    const quantity = offering.quantity.trim();
    if (quantity) {
      if (!/^\d+$/.test(quantity)) add("quantity", "invalid", "Enter a whole number, or leave it empty if you do not know.");
      else if (Number(quantity) > LIMITS.quantityMax) add("quantity", "invalid", `Enter ${LIMITS.quantityMax.toLocaleString("en-US")} or fewer.`);
    }
  }
  return errors;
}

function socialErrors(account: SocialAccountDraft, index: number, all: readonly SocialAccountDraft[]): FieldError[] {
  const errors: FieldError[] = [];
  const base = `socialAccounts.${index}`;
  const add = (field: string, code: FieldErrorCode, message: string) =>
    errors.push({ path: `${base}.${field}`, step: "social", code, message });
  const n = index + 1;

  if (!account.platform) add("platform", "required", `Choose the platform for account ${n}.`);

  const handle = normalizeHandle(account.handle);
  const url = account.url.trim();
  if (!handle && !url) {
    add("handle", "required", `Enter a handle or a profile link for account ${n}.`);
  }
  if (handle) {
    if (looksLikeSecret(handle)) add("handle", "secret", SECRET_MESSAGE);
    else if (!HANDLE.test(handle)) add("handle", "invalid", "A handle can use letters, numbers, dots and underscores, with no spaces.");
  }
  if (url) {
    const problem = validateProfileUrl(url, account.platform);
    if (problem) add("url", "invalid", problem);
  }

  const notes = normalizeText(account.notes);
  if (notes.length > LIMITS.notesMax) add("notes", "too_long", `Notes must be ${LIMITS.notesMax} characters or fewer.`);
  else if (notes && hasControlChars(notes)) add("notes", "invalid", "Notes contain characters that are not allowed.");
  else if (notes && looksLikeSecret(notes)) add("notes", "secret", SECRET_MESSAGE);

  if (account.platform && handle) {
    const duplicateOf = all.findIndex(
      (other, otherIndex) =>
        otherIndex < index && other.platform === account.platform && normalizeHandle(other.handle).toLowerCase() === handle.toLowerCase(),
    );
    if (duplicateOf >= 0) add("handle", "duplicate", `This is the same handle as account ${duplicateOf + 1}. Remove one of them.`);
  }
  return errors;
}

/** Pure validation of the whole draft. Never throws and never mutates its input. */
export function validateProfile(draft: ProfileDraft): ProfileValidation {
  const errors: FieldError[] = [];

  const company = normalizeText(draft.companyName);
  if (!company) errors.push({ path: "companyName", step: "company", code: "required", message: "Enter your company name." });
  else if (company.length < LIMITS.companyNameMin) errors.push({ path: "companyName", step: "company", code: "too_short", message: `The company name must be at least ${LIMITS.companyNameMin} characters.` });
  else if (company.length > LIMITS.companyNameMax) errors.push({ path: "companyName", step: "company", code: "too_long", message: `The company name must be ${LIMITS.companyNameMax} characters or fewer.` });
  else if (hasControlChars(company)) errors.push({ path: "companyName", step: "company", code: "invalid", message: "The company name contains characters that are not allowed." });
  else if (looksLikeSecret(company)) errors.push({ path: "companyName", step: "company", code: "secret", message: SECRET_MESSAGE });

  if (!draft.businessType) {
    errors.push({ path: "businessType", step: "company", code: "required", message: "Choose the business type that fits best." });
  }

  const segmentsLabel = draft.businessType ? BUSINESS_TYPE_META[draft.businessType].segmentsLabel.toLowerCase() : "segments";
  // Categories are not stored by the profile service, so they are optional.
  errors.push(
    ...tagListErrors("categories", draft.categories, null, LIMITS.maxCategories, "Category"),
    ...tagListErrors("segments", draft.segments, `Add at least one entry for ${segmentsLabel}.`, LIMITS.maxSegments, "Segment"),
    ...tagListErrors("targetMarkets", draft.targetMarkets, "Add at least one target market.", LIMITS.maxTargetMarkets, "Market"),
  );

  const noun = draft.businessType ? BUSINESS_TYPE_META[draft.businessType].offeringNoun : "product or service";
  if (draft.offerings.length === 0) {
    errors.push({ path: "offerings", step: "offerings", code: "required", message: `Add at least one ${noun}.` });
  } else if (draft.offerings.length > LIMITS.maxOfferings) {
    errors.push({ path: "offerings", step: "offerings", code: "too_many", message: `Keep the list to ${LIMITS.maxOfferings} entries or fewer.` });
  }
  draft.offerings.forEach((offering, index) => {
    errors.push(...offeringErrors(offering, index, draft.businessType));
    // The profile service rejects two offerings with the same name.
    const name = normalizeText(offering.name).toLowerCase();
    const first = name ? draft.offerings.findIndex((other) => normalizeText(other.name).toLowerCase() === name) : -1;
    if (first >= 0 && first < index) {
      errors.push({ path: `offerings.${index}.name`, step: "offerings", code: "duplicate", message: `This is the same name as ${noun} ${first + 1}. Use a different name or remove one.` });
    }
  });

  if (draft.socialAccounts.length > LIMITS.maxSocialAccounts) {
    errors.push({ path: "socialAccounts", step: "social", code: "too_many", message: `Keep the list to ${LIMITS.maxSocialAccounts} accounts or fewer.` });
  }
  draft.socialAccounts.forEach((account, index) => errors.push(...socialErrors(account, index, draft.socialAccounts)));

  const byStep = Object.fromEntries(STEP_IDS.map((id) => [id, [] as FieldError[]])) as Record<StepId, FieldError[]>;
  for (const error of errors) byStep[error.step].push(error);
  return { errors, byStep, complete: errors.length === 0 };
}
