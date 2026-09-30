/** Arrow-key movement between candidate rows. Returns the next index, or null when the key is not handled. */
export function nextRowIndex(current: number, key: string, length: number): number | null {
  if (length <= 0) return null;
  switch (key) {
    case "ArrowDown":
      return Math.min(current + 1, length - 1);
    case "ArrowUp":
      return Math.max(current - 1, 0);
    case "Home":
      return 0;
    case "End":
      return length - 1;
    default:
      return null;
  }
}
