import { useCallback, useEffect, useMemo, useState } from "react";
import type { PortfolioReviewModel } from "../contracts/ownerResearch";
import { resultToPortfolioModel } from "../lib/adaptPortfolioReadModel";
import { fetchOwnerPortfolioPayload, type PortfolioFetchResult } from "../lib/portfolioApi";

interface KeyedResult {
  /** The request (workspace + load counter) this outcome belongs to. */
  key: string;
  result: PortfolioFetchResult;
}

/**
 * Reads the proposed portfolio read model with a single GET per load.
 * Never writes; a missing endpoint is `unavailable`, a failure is `error`, and
 * neither is ever presented as an empty (0/3) portfolio.
 *
 * The raw fetch outcome is kept, keyed to the request that produced it, and the
 * model is derived with `nowMs` so freshness keeps advancing between fetches. An
 * outcome for any other workspace or load is ignored (treated as loading), so a
 * slow response can never be shown for a workspace that did not ask for it.
 */
export function useOwnerPortfolio(
  workspaceId: string | null,
  options: { fetchImpl?: typeof fetch; nowMs?: number } = {},
): { portfolio: PortfolioReviewModel; refresh: () => void } {
  const selected = workspaceId?.trim() ? workspaceId : null;
  const [nonce, setNonce] = useState(0);
  const [outcome, setOutcome] = useState<KeyedResult | null>(null);
  const { fetchImpl } = options;
  const nowMs = options.nowMs ?? Date.now();
  const currentKey = `${selected ?? ""}#${nonce}`;

  useEffect(() => {
    if (!selected) return undefined;
    const controller = new AbortController();
    void fetchOwnerPortfolioPayload({ workspaceId: selected, fetchImpl, signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) setOutcome({ key: currentKey, result });
    });
    return () => controller.abort();
  }, [selected, fetchImpl, currentKey]);

  const result = outcome !== null && outcome.key === currentKey ? outcome.result : null;
  const portfolio = useMemo(
    () => resultToPortfolioModel(result, { workspaceId: selected, nowMs }),
    [result, selected, nowMs],
  );
  const refresh = useCallback(() => setNonce((value) => value + 1), []);
  return { portfolio, refresh };
}
