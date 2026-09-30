import type { PerformanceSeries } from "../contracts/ownerDashboard.ts";

/**
 * DEMO values invented only to exercise the chart and its gap handling.
 * They are not observed performance. Weeks 4 and 7 are deliberately missing
 * (null) so the UI shows gaps instead of zeros.
 */
export const OWNER_DEMO_PERFORMANCE: PerformanceSeries[] = [
  {
    id: "orders_per_week",
    label: "Orders per week (demo)",
    unit: "count",
    provenance: "fixture",
    points: [
      { periodLabel: "Wk 1", value: 12 },
      { periodLabel: "Wk 2", value: 15 },
      { periodLabel: "Wk 3", value: 14 },
      { periodLabel: "Wk 4", value: null },
      { periodLabel: "Wk 5", value: 19 },
      { periodLabel: "Wk 6", value: 22 },
      { periodLabel: "Wk 7", value: null },
      { periodLabel: "Wk 8", value: 27 },
    ],
  },
];
