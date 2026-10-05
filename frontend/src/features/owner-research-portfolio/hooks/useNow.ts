import { useEffect, useState } from "react";

/**
 * A coarse shared clock. Freshness is derived from "now", so without a tick a
 * page left open would keep reporting "fresh" forever. One re-render a minute.
 */
export function useNow(intervalMs = 60_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}
