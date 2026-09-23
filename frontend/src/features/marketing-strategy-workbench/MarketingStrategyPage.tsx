import { StrategyWorkbench } from "./components/StrategyWorkbench.tsx";
import {
  buildComplete,
  buildConflicting,
  buildPartial,
  buildStale,
} from "./fixtures/buildStrategyFixtures.ts";
import type { MarketingStrategyPacket } from "./contracts/marketingStrategyPacket.ts";
import { buildClientSafeStrategyExport } from "./lib/exportClientSafeStrategy.ts";
import { composePublicityScenario } from "../marketing-publicity-surface/lib/composePublicityScenario.ts";

export type StrategyRouteState = "loading" | "empty" | "unavailable" | "stale" | "conflict" | "partial" | "draft";

function packetFor(state: StrategyRouteState): MarketingStrategyPacket | null {
  if (state === "loading" || state === "empty" || state === "unavailable") return null;
  if (state === "stale") return buildStale();
  if (state === "conflict") return buildConflicting();
  if (state === "partial") return buildPartial();
  return buildComplete("hybrid");
}

/** One planner route. The alias component is not mounted. */
export function MarketingStrategyPage({ state = "draft" }: { state?: StrategyRouteState }) {
  if (state === "loading") {
    return <p role="status" aria-live="polite">Loading the draft strategy plan.</p>;
  }
  const packet = state === "empty" || state === "unavailable" ? null : packetFor(state);
  const scenario = composePublicityScenario(packet, null);
  const exported = packet ? buildClientSafeStrategyExport(packet) : null;
  const exportPreview = exported?.ok
    ? JSON.stringify({ ...exported.body, live_validated: false, launch_authorized: false })
    : "Export withheld. The draft was not published.";
  return (
    <div className="min-w-0">
      <p className="px-4 pt-4 text-sm text-zinc-300" role="status">
        live_validated=false · launch_authorized=false · draft only
        {state === "empty" ? " · empty plan" : ""}
        {state === "unavailable" ? " · unavailable" : ""}
        {scenario.surface === "partial" ? " · partial evidence" : ""}
        {scenario.surface === "stale" ? " · stale evidence" : ""}
        {scenario.surface === "conflicting" ? " · conflicting evidence" : ""}
      </p>
      <StrategyWorkbench scenario={scenario} exportPreview={exportPreview} />
    </div>
  );
}
