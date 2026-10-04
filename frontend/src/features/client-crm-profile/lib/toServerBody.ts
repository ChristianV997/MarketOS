import type { ClientProfileDraftPayload } from "../contracts/clientProfileDraft.ts";

/**
 * The request body the profile service accepts (`api/routes/client_profile.py`).
 * Exactly these keys: the service rejects unknown keys, any workspace/tenant/user
 * selector, any connection claim and anything credential-shaped.
 */
export interface ServerProfileBody {
  company_name: string;
  business_type: string;
  segments: string[];
  target_markets: string[];
  offerings: string[];
  social_accounts: Array<{ platform: string; handle: string }>;
}

/** Form fields the service has nowhere to keep. They stay in the browser tab and are shown as such on the review step. */
export const NOT_STORED_BY_SERVER = [
  "Categories",
  "Offering descriptions, delivery, availability, SKU and units on hand",
  "Social profile links and notes, and any social account entered without a handle",
] as const;

/**
 * Local payload -> service body. Pure and lossy by design: only what the service
 * stores is included. A social account with a link but no handle cannot be
 * stored (the service requires a handle) and is dropped, not invented.
 */
export function toServerBody(payload: ClientProfileDraftPayload): ServerProfileBody {
  return {
    company_name: payload.company_name,
    business_type: payload.business_type,
    segments: [...payload.segments],
    target_markets: [...payload.target_markets],
    offerings: payload.offerings.map((offering) => offering.name),
    social_accounts: payload.social_accounts.flatMap((account) =>
      account.handle ? [{ platform: account.platform, handle: account.handle }] : [],
    ),
  };
}

/** Identity of what the service would store. "Saved" is judged on this, so editing a tab-only field never reads as unsaved. */
export function storedKey(payload: ClientProfileDraftPayload | null): string | null {
  return payload === null ? null : JSON.stringify(toServerBody(payload));
}
