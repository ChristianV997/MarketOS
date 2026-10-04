import { adjacentCandidateIndex, shouldHandoffDetailFocus } from "../../first-phase-cockpit/lib/keyboardNav";

const NAV_KEYS: ReadonlySet<string> = new Set(["ArrowUp", "ArrowDown", "Home", "End"]);

/**
 * What a key press means for the ranked-candidate listbox.
 * - `handled: false`  -> leave the event alone (Tab, typing, browser shortcuts).
 * - `activate`        -> hand focus to the details region.
 * - `move`            -> select and focus `nextIndex`.
 * - `none`            -> consume the key (stops page scroll) but nothing changes,
 *                        e.g. ArrowDown on the last option. No wrap-around.
 */
export type ListboxKeyAction =
  | { handled: false }
  | { handled: true; kind: "activate" }
  | { handled: true; kind: "move"; nextIndex: number }
  | { handled: true; kind: "none" };

export function resolveListboxKey(
  event: { key: string; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean },
  index: number,
  length: number,
): ListboxKeyAction {
  if (length <= 0) return { handled: false };
  // Ctrl/Cmd/Alt combinations belong to the browser and OS (Ctrl+End, Alt+Left, ...).
  if (event.ctrlKey || event.metaKey || event.altKey) return { handled: false };
  if (shouldHandoffDetailFocus(event.key)) return { handled: true, kind: "activate" };
  if (!NAV_KEYS.has(event.key)) return { handled: false };
  const nextIndex = adjacentCandidateIndex(length, index, event.key);
  return nextIndex < 0 || nextIndex === index
    ? { handled: true, kind: "none" }
    : { handled: true, kind: "move", nextIndex };
}
