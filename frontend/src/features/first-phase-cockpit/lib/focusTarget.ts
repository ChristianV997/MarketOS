/**
 * Focus targets for the ranked-candidate lists.
 *
 * The mobile listbox and the desktop table both render every visible candidate, and CSS hides one of
 * the two copies at each breakpoint. An element that is not laid out cannot take focus, so a lookup by
 * candidate id has to choose among the copies that are rendered.
 */

export interface LayoutCheckable {
  getClientRects(): ArrayLike<unknown>;
}

export function isLaidOut(element: LayoutCheckable): boolean {
  return element.getClientRects().length > 0;
}

export function firstLaidOut<T extends LayoutCheckable>(elements: readonly T[]): T | null {
  for (const element of elements) {
    if (isLaidOut(element)) return element;
  }
  return null;
}

/**
 * Elements carrying exactly this candidate id. The ids are compared rather than interpolated into a
 * selector, so an id containing quotes or backslashes cannot make the lookup throw.
 */
export function candidateElements(root: ParentNode | null, candidateId: string): HTMLElement[] {
  if (!root) return [];
  return Array.from(root.querySelectorAll<HTMLElement>("[data-candidate-id]")).filter(
    (element) => element.dataset.candidateId === candidateId,
  );
}
