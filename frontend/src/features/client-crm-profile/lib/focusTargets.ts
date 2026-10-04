import { fieldId } from "./validateProfile.ts";

/**
 * DOM id to focus for a field path. List-level problems (no offerings yet)
 * have no input of their own, so they point at the list's "Add" button.
 */
export function focusId(path: string): string {
  if (path === "offerings" || path === "offerings-add") return "cp-offerings-add";
  if (path === "socialAccounts" || path === "socialAccounts-add") return "cp-socialAccounts-add";
  return fieldId(path);
}
