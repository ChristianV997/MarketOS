import {
  BUSINESS_TYPE_META,
  CLIENT_PROFILE_DRAFT_SCHEMA_VERSION,
  type ClientProfileDraftPayload,
  type ProfileDraft,
  type ProductAvailability,
  type ServiceDelivery,
  type SocialPlatform,
} from "../contracts/clientProfileDraft.ts";
import { dedupeCaseInsensitive, normalizeText } from "./text.ts";
import { normalizeHandle, validateProfile } from "./validateProfile.ts";

/**
 * Draft -> payload. Fail-closed: returns null unless the whole draft validates,
 * so an incomplete or invalid profile can never be handed to a persistence
 * function. Only fields that belong to the chosen business type are included
 * (a product's SKU never leaks into a service profile), and an empty quantity
 * stays null, never 0.
 */
export function buildPayload(draft: ProfileDraft): ClientProfileDraftPayload | null {
  if (!validateProfile(draft).complete || draft.businessType === null) return null;
  const tracksInventory = BUSINESS_TYPE_META[draft.businessType].tracksInventory;

  return {
    schema_version: CLIENT_PROFILE_DRAFT_SCHEMA_VERSION,
    company_name: normalizeText(draft.companyName),
    business_type: draft.businessType,
    categories: dedupeCaseInsensitive(draft.categories.map(normalizeText)),
    segments: dedupeCaseInsensitive(draft.segments.map(normalizeText)),
    target_markets: dedupeCaseInsensitive(draft.targetMarkets.map(normalizeText)),
    offerings: draft.offerings.map((offering) => {
      const base = { name: normalizeText(offering.name), description: normalizeText(offering.description) || null };
      if (!tracksInventory) {
        return offering.delivery === "" ? base : { ...base, delivery: offering.delivery as ServiceDelivery };
      }
      const quantity = offering.quantity.trim();
      return {
        ...base,
        ...(offering.availability === "" ? {} : { availability: offering.availability as ProductAvailability }),
        sku: offering.sku.trim() || null,
        quantity: quantity === "" ? null : Number(quantity),
      };
    }),
    social_accounts: draft.socialAccounts.map((account) => ({
      platform: account.platform as SocialPlatform,
      handle: normalizeHandle(account.handle) || null,
      url: account.url.trim() || null,
      notes: normalizeText(account.notes) || null,
      link_status: "not_connected" as const,
    })),
  };
}

/** Stable identity of a payload; used to know whether "saved" still describes the form. */
export function payloadKey(payload: ClientProfileDraftPayload | null): string | null {
  return payload === null ? null : JSON.stringify(payload);
}
