export { ConsultingResearchSurface } from "./components/ConsultingResearchSurface.tsx";
export { ConsultingResearchSurfacePage } from "./ConsultingResearchSurfacePage.tsx";
export { adaptResearchSurface, normalizeClass } from "./lib/adaptResearchSurface.ts";
export { composeResearchSurface, moveSelection } from "./lib/composeResearchSurface.ts";
export { buildClientSafeSurfaceExport } from "./lib/exportResearchSurface.ts";
export { buildSurfaceFixture } from "./fixtures/surfaceFixture.ts";
export { mapMarketResearchReport, MARKET_RESEARCH_REPORT_VERSION } from "./lib/mapMarketResearchReport.ts";
export {
  ingestLocalResearchReportJson,
  loadLocalResearchReportFile,
  localReportRejectionMessage,
  MAX_LOCAL_RESEARCH_REPORT_BYTES,
} from "./lib/loadLocalResearchReport.ts";
export {
  LIVE_RESEARCH_REPORT_ENDPOINT,
  LIVE_RESEARCH_REQUEST_VERSION,
  buildLiveResearchRequest,
  liveResearchBoundaryCopy,
} from "./contracts/liveResearchReport.ts";
export { fetchLiveResearchReport, buildLiveResearchReportUrl } from "./lib/liveResearchReportApi.ts";
export {
  adaptLiveResearchResponse,
  assertLiveEvidenceClasses,
  mapRecognizedEvidenceStatus,
  observationsFromSurfaceModel,
  unwrapLiveResearchEnvelope,
} from "./lib/adaptLiveResearchResponse.ts";
export type { LiveResearchEvidenceLabel } from "./lib/adaptLiveResearchResponse.ts";
