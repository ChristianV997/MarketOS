import type { ProfileErrorCode } from "../contracts/clientProfileDraft.ts";

/** Client-facing wording per failure. Raw server text is never shown. */
export const SAVE_ERROR_TEXT: Record<ProfileErrorCode, string> = {
  unauthenticated: "You are not signed in, so nothing was saved.",
  forbidden: "This account is not allowed to save this profile. Nothing was saved.",
  not_found: "The profile service could not be found. Nothing was saved.",
  conflict: "The profile was changed elsewhere. Reload the page to see the latest saved version; nothing was overwritten.",
  unavailable: "The profile service is unavailable right now. Nothing was saved. Try again later.",
  malformed_response: "The server replied in a way this page could not read, so it cannot confirm anything was saved.",
  network: "The server could not be reached. Nothing was saved.",
  validation: "The server rejected some values. Nothing was saved. Review the entries and try again.",
  content_rejected: "The server's content screen rejected a value, for example one that contains a word such as \"token\", \"strategy\", \"formula\" or \"prompt\", or a \"/\" after a space. Nothing was saved. Reword the entries and try again.",
  unknown: "Something went wrong. Nothing was confirmed as saved. Try again.",
};

export const LOAD_ERROR_TEXT: Record<ProfileErrorCode, string> = {
  unauthenticated: "A sign-in is required to load a saved profile, and no sign-in is connected to this page yet.",
  forbidden: "This account is not allowed to view a client profile.",
  not_found: "The profile service could not be found, so this page cannot tell whether a profile exists.",
  conflict: "The profile is being changed elsewhere. Try again in a moment.",
  unavailable: "The profile service is unavailable right now. Try again later.",
  malformed_response: "The server replied in a way this page could not read. Nothing was changed.",
  network: "The server could not be reached. Check your connection and try again.",
  validation: "The server rejected the request.",
  content_rejected: "The server's content screen rejected the request.",
  unknown: "Something went wrong while loading the profile.",
};
