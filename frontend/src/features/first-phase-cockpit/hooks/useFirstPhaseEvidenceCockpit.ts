import {
  useBenchmarkMatrix,
  usePhase1Readiness,
  usePublicMarketBenchmark,
  useResearchPortfolios,
} from "@/hooks/useCanonicalEvents";
import {
  composeCockpitViewModel,
  extractExistingResearchToDecisionProjection,
} from "../lib/composeCockpitViewModel";
import type { FirstPhaseEvidencePacket } from "../contracts/firstPhaseEvidencePacket";

export function useFirstPhaseEvidenceCockpit(): {
  packet: FirstPhaseEvidencePacket;
  isLoading: boolean;
  hasErrors: boolean;
} {
  const phase1Readiness = usePhase1Readiness();
  const benchmark = useBenchmarkMatrix();
  const publicMarket = usePublicMarketBenchmark();
  const research = useResearchPortfolios({ source: "jsonl", limit: 1 });

  const isLoading =
    phase1Readiness.isLoading
    || benchmark.isLoading
    || publicMarket.isLoading
    || research.isLoading;

  const researchPortfolio = research.data?.portfolios?.[0] ?? null;
  const packet = composeCockpitViewModel({
    phase1Readiness: phase1Readiness.data ?? null,
    benchmark: benchmark.data ?? null,
    publicMarket: publicMarket.data ?? null,
    researchPortfolio,
    readinessError: Boolean(phase1Readiness.error),
    benchmarkError: Boolean(benchmark.error),
    publicMarketError: Boolean(publicMarket.error),
    researchError: Boolean(research.error),
    isLoading,
    researchToDecisionProjection: extractExistingResearchToDecisionProjection(
      undefined,
      researchPortfolio,
    ),
    commerceProjection: undefined,
    operatorWorkspaceId: researchPortfolio?.workspace_id ?? null,
  });

  return {
    packet,
    isLoading,
    hasErrors: Boolean(
      phase1Readiness.error || benchmark.error || publicMarket.error || research.error,
    ),
  };
}
