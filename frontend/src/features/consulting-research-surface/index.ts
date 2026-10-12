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
