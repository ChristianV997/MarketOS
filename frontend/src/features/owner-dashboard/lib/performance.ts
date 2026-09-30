import type { PerformanceModel, PerformancePoint, PerformanceSeries } from "../contracts/ownerDashboard.ts";

export interface ChartRow {
  period: string;
  [seriesId: string]: string | number | null;
}

function cleanPoint(point: PerformancePoint): PerformancePoint {
  const value = typeof point.value === "number" && Number.isFinite(point.value) ? point.value : null;
  return { periodLabel: point.periodLabel, value };
}

/**
 * A chart is only offered when at least one real value exists. Missing values stay
 * null (a gap), never zero. Any fixture-provenance series labels the whole panel
 * as demo data; "observed" is only claimed when every kept series is observed.
 */
export function composePerformance(series: PerformanceSeries[] | null): PerformanceModel {
  if (!series || series.length === 0) {
    return { status: "unavailable", reason: "No observed performance records are connected to this dashboard." };
  }
  const kept = series
    .map((item) => ({ ...item, points: item.points.map(cleanPoint) }))
    .filter((item) => item.points.some((point) => point.value !== null));
  if (kept.length === 0) {
    return { status: "unavailable", reason: "Performance records were provided, but none contain a value." };
  }
  const missingPoints = kept.reduce((total, item) => total + item.points.filter((point) => point.value === null).length, 0);
  const allObserved = kept.every((item) => item.provenance === "observed");
  return { status: allObserved ? "observed" : "fixture_demo", series: kept, missingPoints };
}

export function buildChartRows(series: PerformanceSeries[]): ChartRow[] {
  const order: string[] = [];
  const rows = new Map<string, ChartRow>();
  for (const item of series) {
    for (const point of item.points) {
      let row = rows.get(point.periodLabel);
      if (!row) {
        row = { period: point.periodLabel };
        rows.set(point.periodLabel, row);
        order.push(point.periodLabel);
      }
      row[item.id] = point.value;
    }
  }
  return order.map((period) => rows.get(period) as ChartRow);
}
