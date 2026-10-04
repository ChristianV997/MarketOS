export {
  OWNER_PERFORMANCE_SCHEMA,
  CONTRACT_HEAD,
  OWNER_PERFORMANCE_API_PATH,
  MEASURE_KEYS,
  MEASURE_LABELS,
  type MeasureKey,
  type MoneyView,
  type CampaignRow,
  type OwnerPerformanceReport,
} from "./contracts/ownerPerformanceReport.ts";

export {
  default as OwnerPerformanceDashboard,
  OwnerPerformanceDashboardView,
  type DashboardPhase,
  type OwnerPerformanceDashboardProps,
} from "./components/OwnerPerformanceDashboard.tsx";

export {
  fetchOwnerPerformanceReport,
  OwnerPerformanceApiError,
  OwnerPerformanceAuthError,
  OwnerPerformanceUnavailableError,
} from "./lib/fetchOwnerPerformance.ts";

export {
  useOwnerPerformance,
  type UseOwnerPerformanceOptions,
  type UseOwnerPerformanceResult,
} from "./hooks/useOwnerPerformance.ts";

export {
  presentMeasure,
  presentMeasures,
  presentCampaigns,
  reportHasFixtureEvidence,
  assertReportContract,
  textSummary,
  type MeasureDisplay,
  type CampaignDisplay,
} from "./lib/presentReport.ts";

export { DEMO_OBSERVED_REPORT, DEMO_PARTIAL_REPORT } from "./fixtures/demoReport.ts";
