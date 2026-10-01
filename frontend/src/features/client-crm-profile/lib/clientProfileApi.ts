import { joinApiPath, resolveApiBaseUrl } from "../../../lib/apiBase.ts";
import {
  ProfileSaveError,
  type ClientProfileDraftPayload,
  type ProfileDraft,
  type ProfileErrorCode,
} from "../contracts/clientProfileDraft.ts";
import { parseServerProfile } from "./serverProfile.ts";

/**
 * The only network code in this feature. One same-origin endpoint, three methods:
 *   GET   -> read the signed-in client's profile
 *   POST  -> create it (when GET said there is none)
 *   PATCH -> update it
 * There is deliberately no workspace, tenant or client identifier anywhere in the
 * URL, headers or body: the server decides whose profile this is from the
 * session cookie. `credentials: "same-origin"` sends that cookie and nothing else.
 *
 * ASSUMPTION (the backend contract is not in this repository yet): request and
 * response bodies use the client-profile-draft-v0 shape from
 * `contracts/clientProfileDraft.ts`. If the real contract differs, only this file
 * and `serverProfile.ts` change.
 */
export const CLIENT_PROFILE_ENDPOINT = "/api/organization/client-profile";
export const MAX_RESPONSE_CHARS = 256 * 1024;

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;
export interface ClientProfileApiOptions {
  fetchImpl?: FetchLike;
  baseUrl?: string;
  signal?: AbortSignal;
}

export type LoadResult =
  | { kind: "ok"; draft: ProfileDraft }
  | { kind: "not_found" }
  | { kind: "error"; code: ProfileErrorCode }
  | { kind: "aborted" };

export type SaveMode = "create" | "update";

/** Non-2xx status -> the failure code the UI words differently. */
export function codeForStatus(status: number): ProfileErrorCode {
  switch (status) {
    case 401: return "unauthenticated";
    case 403: return "forbidden";
    case 404: return "not_found";
    case 409: return "conflict";
    case 503: return "unavailable";
    case 400:
    case 422: return "validation";
    default: return "unknown";
  }
}

type Outcome = { kind: "response"; status: number; body: unknown | undefined; unreadable: boolean } | { kind: "network" } | { kind: "aborted" };

async function send(method: "GET" | "POST" | "PATCH", payload: ClientProfileDraftPayload | null, options: ClientProfileApiOptions): Promise<Outcome> {
  const fetchImpl: FetchLike = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const url = joinApiPath(options.baseUrl ?? resolveApiBaseUrl(), CLIENT_PROFILE_ENDPOINT);
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: payload ? { Accept: "application/json", "Content-Type": "application/json" } : { Accept: "application/json" },
      body: payload ? JSON.stringify(payload) : undefined,
      signal: options.signal,
    });
  } catch {
    return options.signal?.aborted ? { kind: "aborted" } : { kind: "network" };
  }

  if (response.status < 200 || response.status >= 300) {
    return { kind: "response", status: response.status, body: undefined, unreadable: false };
  }
  let text: string;
  try {
    text = await response.text();
  } catch {
    return options.signal?.aborted ? { kind: "aborted" } : { kind: "network" };
  }
  if (text.trim() === "") return { kind: "response", status: response.status, body: undefined, unreadable: false };
  if (text.length > MAX_RESPONSE_CHARS) return { kind: "response", status: response.status, body: undefined, unreadable: true };
  try {
    return { kind: "response", status: response.status, body: JSON.parse(text) as unknown, unreadable: false };
  } catch {
    return { kind: "response", status: response.status, body: undefined, unreadable: true };
  }
}

/** GET. 404 means "no saved profile yet", which is a normal first-visit state, not a failure. */
export async function fetchClientProfile(options: ClientProfileApiOptions = {}): Promise<LoadResult> {
  const outcome = await send("GET", null, options);
  if (outcome.kind === "aborted") return { kind: "aborted" };
  if (outcome.kind === "network") return { kind: "error", code: "network" };
  if (outcome.status === 404) return { kind: "not_found" };
  if (outcome.status !== 200) return { kind: "error", code: outcome.status >= 200 && outcome.status < 300 ? "malformed_response" : codeForStatus(outcome.status) };
  if (outcome.unreadable) return { kind: "error", code: "malformed_response" };
  const draft = parseServerProfile(outcome.body);
  return draft ? { kind: "ok", draft } : { kind: "error", code: "malformed_response" };
}

/**
 * POST (create) or PATCH (update). Resolves only after a 2xx response that can be
 * trusted: 200/201 must carry a valid profile, 204 carries nothing to check.
 * Everything else throws a ProfileSaveError with a distinct code, so the caller
 * can never show "saved" for a failure or an unreadable reply.
 */
export async function saveClientProfile(mode: SaveMode, payload: ClientProfileDraftPayload, options: ClientProfileApiOptions = {}): Promise<void> {
  const outcome = await send(mode === "create" ? "POST" : "PATCH", payload, options);
  if (outcome.kind === "aborted") throw new ProfileSaveError("network");
  if (outcome.kind === "network") throw new ProfileSaveError("network");
  const { status } = outcome;
  if (status < 200 || status >= 300) throw new ProfileSaveError(codeForStatus(status));
  if (status === 204) return;
  if (status !== 200 && status !== 201) throw new ProfileSaveError("malformed_response");
  if (outcome.unreadable || parseServerProfile(outcome.body) === null) throw new ProfileSaveError("malformed_response");
}
