import { useCallback, useEffect, useState } from "react";
import type { PortfolioReviewModel } from "../contracts/ownerResearch";
import {
  adaptPortfolioPayload,
  portfolioError,
  portfolioLoading,
  portfolioUnavailable,
} from "../lib/adaptPortfolioReadModel";
import { fetchOwnerPortfolioPayload } from "../lib/portfolioApi";

/**
 * Reads the proposed portfolio read model with a single GET per load.
 * Never writes; a missing endpoint is `unavailable`, a failure is `error`, and
 * neither is ever presented as an empty (0/3) portfolio.
 */
export function useOwnerPortfolio(
  workspaceId: string | null,
  options: { fetchImpl?: typeof fetch } = {},
): { portfolio: PortfolioReviewModel; refresh: () => void } {
  const selected = workspaceId?.trim() ? workspaceId : null;
  const [portfolio, setPortfolio] = useState<PortfolioReviewModel>(() =>
    selected ? portfolioLoading(selected) : portfolioUnavailable("workspace_not_selected"),
  );
  const [nonce, setNonce] = useState(0);
  const { fetchImpl } = options;

  useEffect(() => {
    if (!selected) {
      setPortfolio(portfolioUnavailable("workspace_not_selected"));
      return undefined;
    }
    const controller = new AbortController();
    setPortfolio(portfolioLoading(selected));
    void fetchOwnerPortfolioPayload({ workspaceId: selected, fetchImpl, signal: controller.signal }).then((result) => {
      if (controller.signal.aborted) return;
      if (result.kind === "ok") {
        setPortfolio(adaptPortfolioPayload(result.payload, { expectedWorkspaceId: selected, nowMs: Date.now() }));
      } else if (result.kind === "unavailable") {
        setPortfolio(portfolioUnavailable(result.reason, selected));
      } else {
        setPortfolio(portfolioError(result.reason, selected));
      }
    });
    return () => controller.abort();
  }, [selected, fetchImpl, nonce]);

  const refresh = useCallback(() => setNonce((value) => value + 1), []);
  return { portfolio, refresh };
}
