import { joinApiPath, resolveApiBaseUrl } from "../../../lib/apiBase.ts";
import {
  ProfileSaveError,
  type ClientProfileDraftPayload,
  type ProfileDraft,
  type ProfileErrorCode,
} from "../contracts/clientProfileDraft.ts";
import { parseServerProfile } from "./serverProfile.ts";
import { toServerBody } from "./toServerBody.ts";

/**
 * The only network code in this feature. One endpoint, three methods, the
 * contract in `api/routes/client_profile.py`:
 *   GET   -> read the caller's profile (404 = none yet)
 *   POST  -> create it
 *   PATCH -> replace the fields sent
 * Authentication is `Authorization: Bearer <token>` from an injected
 * `getAccessToken`. The token is read per request, never stored here, never
 * typed into this feature and never logged. There is deliberately no workspace,
 * tenant or user identifier in the URL, headers or body: the server resolves the
 * workspace from the verified token, and rejects a body that names one.
 * `credentials: "omit"` keeps cookies out of it entirely.
 *
 * Nothing in this repository issues those tokens yet, so the mounted routes pass
 * no `getAccessToken` and never reach this file (they run the offline demo).
 */
export const CLIENT_PROFILE_ENDPOINT = "/api/organization/client-profile";
export const MAX_RESPONSE_CHARS = 256 * 1024;

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;
/** Supplies the caller's bearer token, or null when there is no signed-in session. Called once per request. */
export type AccessTokenProvider = () => Promise<string | null>;

export interface ClientProfileApiOptions {
  /** Without it no request is made: the result is `unauthenticated`. */
  getAccessToken?: AccessTokenProvider;
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

/** Service error codes (`detail.code`) that mean its content screen refused a value. */
const CONTENT_SCREEN_CODES: readonly string[] = ["content_rejected", "credentials_rejected"];

/** Non-2xx status (and the service's own `detail.code`, when it sent one) -> the failure code the UI words differently. */
export function codeForStatus(status: number, detailCode?: string | null): ProfileErrorCode {
  if (status === 422 && detailCode && CONTENT_SCREEN_CODES.includes(detailCode)) return "content_rejected";
  switch (status) {
    case 401: return "unauthenticated";
    case 403: return "forbidden";
    case 404: return "not_found";
    case 409: return "conflict";
    case 503: return "unavailable";
    case 400:
    case 413:
    case 415:
    case 422: return "validation";
    default: return "unknown";
  }
}

type Outcome =
  | { kind: "response"; status: number; body: unknown | undefined; unreadable: boolean; detailCode: string | null }
  | { kind: "network" }
  | { kind: "aborted" };

/** The service's error body is `{detail: {code}}`. Only a short snake_case code is ever read; no other text is kept. */
async function readDetailCode(response: Response): Promise<string | null> {
  try {
    const text = await response.text();
    if (text.length > 4096) return null;
    const detail = (JSON.parse(text) as { detail?: { code?: unknown } } | null)?.detail;
    const code = detail && typeof detail === "object" ? detail.code : undefined;
    return typeof code === "string" && /^[a-z_]{1,64}$/.test(code) ? code : null;
  } catch {
    return null;
  }
}

async function readToken(options: ClientProfileApiOptions): Promise<string | null> {
  try {
    const token = await options.getAccessToken?.();
    return typeof token === "string" && token.trim() !== "" ? token.trim() : null;
  } catch {
    return null;
  }
}

async function send(method: "GET" | "POST" | "PATCH", payload: ClientProfileDraftPayload | null, options: ClientProfileApiOptions): Promise<Outcome> {
  const token = await readToken(options);
  if (options.signal?.aborted) return { kind: "aborted" };
  if (token === null) return { kind: "response", status: 401, body: undefined, unreadable: false, detailCode: null };
  const fetchImpl: FetchLike = options.fetchImpl ?? ((input, init) => fetch(input, init));
  const url = joinApiPath(options.baseUrl ?? resolveApiBaseUrl(), CLIENT_PROFILE_ENDPOINT);
  let response: Response;
  try {
    response = await fetchImpl(url, {
      method,
      credentials: "omit",
      cache: "no-store",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${token}`,
        ...(payload ? { "Content-Type": "application/json" } : {}),
      },
      body: payload ? JSON.stringify(toServerBody(payload)) : undefined,
      signal: options.signal,
    });
  } catch {
    return options.signal?.aborted ? { kind: "aborted" } : { kind: "network" };
  }

  if (response.status < 200 || response.status >= 300) {
    return { kind: "response", status: response.status, body: undefined, unreadable: false, detailCode: await readDetailCode(response) };
  }
  let text: string;
  try {
    text = await response.text();
  } catch {
    return options.signal?.aborted ? { kind: "aborted" } : { kind: "network" };
  }
  if (text.trim() === "") return { kind: "response", status: response.status, body: undefined, unreadable: false, detailCode: null };
  if (text.length > MAX_RESPONSE_CHARS) return { kind: "response", status: response.status, body: undefined, unreadable: true, detailCode: null };
  try {
    return { kind: "response", status: response.status, body: JSON.parse(text) as unknown, unreadable: false, detailCode: null };
  } catch {
    return { kind: "response", status: response.status, body: undefined, unreadable: true, detailCode: null };
  }
}

/** GET. A 404 carrying `detail.code: "profile_not_found"` means "no saved profile yet", a normal first-visit state; any other 404 is an error. */
export async function fetchClientProfile(options: ClientProfileApiOptions = {}): Promise<LoadResult> {
  const outcome = await send("GET", null, options);
  if (outcome.kind === "aborted") return { kind: "aborted" };
  if (outcome.kind === "network") return { kind: "error", code: "network" };
  // Only the service's own "no profile yet" answer is a first visit. Any other 404 (wrong base URL, missing route, proxy) is an error.
  if (outcome.status === 404) return outcome.detailCode === "profile_not_found" ? { kind: "not_found" } : { kind: "error", code: "not_found" };
  if (outcome.status !== 200) return { kind: "error", code: outcome.status >= 200 && outcome.status < 300 ? "malformed_response" : codeForStatus(outcome.status, outcome.detailCode) };
  if (outcome.unreadable) return { kind: "error", code: "malformed_response" };
  const draft = parseServerProfile(outcome.body);
  return draft ? { kind: "ok", draft } : { kind: "error", code: "malformed_response" };
}

/**
 * POST (create) or PATCH (update). Resolves only after a 2xx response that can be
 * trusted: the service answers 201 (create) or 200 (update) with the stored
 * profile, and that body must parse. Anything else, a 204 included, is not a
 * confirmation.
 * Everything else throws a ProfileSaveError with a distinct code, so the caller
 * can never show "saved" for a failure or an unreadable reply.
 */
export async function saveClientProfile(mode: SaveMode, payload: ClientProfileDraftPayload, options: ClientProfileApiOptions = {}): Promise<void> {
  const outcome = await send(mode === "create" ? "POST" : "PATCH", payload, options);
  if (outcome.kind === "aborted") throw new ProfileSaveError("network");
  if (outcome.kind === "network") throw new ProfileSaveError("network");
  const { status } = outcome;
  if (status < 200 || status >= 300) throw new ProfileSaveError(codeForStatus(status, outcome.detailCode));
  if (status !== 200 && status !== 201) throw new ProfileSaveError("malformed_response");
  if (outcome.unreadable || parseServerProfile(outcome.body) === null) throw new ProfileSaveError("malformed_response");
}
