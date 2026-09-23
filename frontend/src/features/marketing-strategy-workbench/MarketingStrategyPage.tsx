import { useSearchParams } from "react-router-dom";
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

const FIXTURE_STATES = new Set<StrategyRouteState>(["loading", "empty", "unavailable", "stale", "conflict", "partial", "draft"]);

function fixtureStateFromSearch(params: URLSearchParams, fallback: StrategyRouteState): StrategyRouteState {
  const requested = params.get("state");
  if (requested && FIXTURE_STATES.has(requested as StrategyRouteState)) return requested as StrategyRouteState;
  return fallback;
}

/** One planner route. The alias component is not mounted. `?state=` selects a local fixture only. */
export function MarketingStrategyPage({ state = "draft" }: { state?: StrategyRouteState }) {
  const [params] = useSearchParams();
  state = fixtureStateFromSearch(params, state);
  if (state === "loading") {
    return <p role="status" aria-live="polite">Loading the draft strategy plan.</p>;
  }
  const packet = state === "empty" || state === "unavailable" ? null : packetFor(state);
  const composed = composePublicityScenario(packet, null);
  const scenario = state === "empty"
    ? { ...composed, title: "Empty strategy plan", banner: "Empty plan. No draft packet is loaded. Not an executed campaign." }
    : composed;
  const exported = packet ? buildClientSafeStrategyExport(packet) : null;
  const exportPreview = exported?.ok
    ? JSON.stringify({ ...exported.body, live_validated: false, launch_authorized: false })
    : "Export withheld. The draft was not published.";
  return (
    <div className="min-w-0">
      <p className="px-4 pt-4 text-sm text-zinc-300" role="status">
        draft_only=true · live_validated=false · launch_authorized=false · draft only
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
