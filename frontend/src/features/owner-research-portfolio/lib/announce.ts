import type { OpportunityReviewModel, PortfolioReviewModel, SurfaceQualifier } from "../contracts/ownerResearch";

const RANKING_TEXT: Record<Exclude<OpportunityReviewModel["phase"], "ready">, string> = {
  loading: "Ranking is loading.",
  error: "Ranking failed to load.",
  unavailable: "Ranking is unavailable.",
  empty: "Ranking loaded with no candidates.",
};

const PORTFOLIO_UNKNOWN_TEXT: Record<"loading" | "error" | "unavailable", string> = {
  loading: "Portfolio is loading.",
  error: "Portfolio failed to load.",
  unavailable: "Portfolio is unavailable.",
};

/**
 * One sentence for the persistent polite live region, so loading -> ready and
 * count changes are announced (a freshly mounted role="status" is unreliable).
 * An unknown portfolio is never announced as zero.
 */
export function announceSurface(ranking: OpportunityReviewModel, portfolio: PortfolioReviewModel): string {
  const rankingText =
    ranking.phase === "ready"
      ? `Ranking ready: ${ranking.rows.length} candidate${ranking.rows.length === 1 ? "" : "s"} in backend order.`
      : RANKING_TEXT[ranking.phase];

  const portfolioText =
    portfolio.activeCount === null
      ? PORTFOLIO_UNKNOWN_TEXT[portfolio.phase as "loading" | "error" | "unavailable"] ?? "Portfolio is unavailable."
      : `Portfolio: ${portfolio.activeCount} of ${portfolio.required} distinct active candidates.`;

  const qualifiers: SurfaceQualifier[] = [];
  for (const qualifier of [...ranking.qualifiers, ...portfolio.qualifiers]) {
    if (!qualifiers.includes(qualifier)) qualifiers.push(qualifier);
  }
  const qualifierText = qualifiers.length > 0 ? ` Notices: ${qualifiers.join(", ")}.` : "";

  return `${rankingText} ${portfolioText}${qualifierText}`;
}
