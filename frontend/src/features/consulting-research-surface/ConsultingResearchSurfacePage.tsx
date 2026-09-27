import { ConsultingResearchSurface } from "./components/ConsultingResearchSurface.tsx";
import { buildSurfaceFixture } from "./fixtures/surfaceFixture.ts";

/** Mountable page. Not registered in the shared router by this feature. */
export function ConsultingResearchSurfacePage() {
  return <ConsultingResearchSurface packet={buildSurfaceFixture()} />;
}
