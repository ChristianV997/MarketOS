import type { OwnerDashboardSource } from "../contracts/ownerDashboard.ts";
import { OWNER_DEMO_DISCOVERY_RUN } from "../fixtures/ownerDemoDiscoveryRun.ts";
import { OWNER_DEMO_PERFORMANCE } from "../fixtures/ownerDemoPerformance.ts";

/**
 * The only source today. It returns bundled demo data and makes no request.
 *
 * A live source must not be added until an authorized, workspace-scoped read
 * endpoint exists (verified identity and workspace resolution on the server,
 * never a client-supplied workspace). Until then the dashboard cannot show
 * private records, and the UI says so.
 */
export const fixtureSource: OwnerDashboardSource = {
  id: "fixture-demo",
  dataMode: "fixture_demo",
  load: async () => ({
    run: OWNER_DEMO_DISCOVERY_RUN,
    asOf: null,
    performance: OWNER_DEMO_PERFORMANCE,
  }),
};
