import { useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useRuntimeStore } from "../runtimeStore";
import type { RuntimeSnapshot, RuntimeEnvelope } from "../types";
import { DeploymentTimeline } from "./DeploymentTimeline";
import { AgentActivity } from "./AgentActivity";
import { InventoryOps } from "./InventoryOps";
import { ClaudeStrategyFeed } from "./ClaudeStrategyFeed";
import { ReplayInspector } from "./ReplayInspector";
import { OperatorQuickActions } from "./OperatorQuickActions";
import { DesktopWorkspace } from "./DesktopWorkspace";

interface Props {
  snapshot: RuntimeSnapshot | null;
  connected: boolean;
}

interface RuntimeStats {
  deployments: number;
  successes: number;
  failures: number;
  uniqueHashes: number;
  lastSequence: number;
  products: { name: string; score: number }[];
  creatives: { name: string; score: number }[];
}

function getType(event: RuntimeEnvelope): string {
  return String(event.type || "unknown").toLowerCase();
}

function buildStats(events: RuntimeEnvelope[]): RuntimeStats {
  const replayHashes = new Set<string>();
  let deployments = 0;
  let successes = 0;
  let failures = 0;
  let lastSequence = 0;

  const productScores = new Map<string, number>();
  const creativeScores = new Map<string, number>();

  events.forEach((event) => {
    const type = getType(event);

    if (event.replay_hash) {
      replayHashes.add(event.replay_hash);
    }

    if (typeof event.sequence_id === "number") {
      lastSequence = Math.max(lastSequence, event.sequence_id);
    }

    if (type.includes("deploy")) deployments += 1;
    if (type.includes("success")) successes += 1;
    if (type.includes("fail")) failures += 1;

    const payload = (event.payload || {}) as Record<string, unknown>;

    const product = String(payload.product || payload.sku || "");
    const creative = String(payload.creative || payload.hook || "");

    const roas = Number(payload.roas || payload.predicted_roas || 0);
    const conversions = Number(payload.conversions || payload.ctr || 0);

    const score = roas + conversions;

    if (product) {
      productScores.set(product, (productScores.get(product) || 0) + score);
    }

    if (creative) {
      creativeScores.set(creative, (creativeScores.get(creative) || 0) + score);
    }
  });

  return {
    deployments,
    successes,
    failures,
    uniqueHashes: replayHashes.size,
    lastSequence,
    products: [...productScores.entries()]
      .map(([name, score]) => ({ name, score }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 5),
    creatives: [...creativeScores.entries()]
      .map(([name, score]) => ({ name, score }))
      .sort((a, b) => b.score - a.score)
      .slice(0, 5),
  };
}

async function trigger(endpoint: string) {
  await fetch(endpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
  });
}

export function CommandCenter({ snapshot, connected }: Props) {
  const events = useRuntimeStore((state) => state.events);
  const [busy, setBusy] = useState<string | null>(null);

  const stats = useMemo(() => buildStats(events), [events]);

  const chartData = useMemo(() => {
    return events.slice(-40).map((event, index) => ({
      index,
      sequence: event.sequence_id || index,
    }));
  }, [events]);

  const recentEvents = useMemo(() => {
    return [...events].reverse().slice(0, 12);
  }, [events]);

  const executeControl = async (action: string, endpoint: string) => {
    try {
      setBusy(action);
      await trigger(endpoint);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
        <div className="bg-black border border-zinc-800 rounded-2xl p-5">
          <div className="text-zinc-500 text-sm">Runtime Status</div>

          <div className="mt-3 flex items-center gap-3">
            <div className={`w-3 h-3 rounded-full ${connected ? "bg-emerald-400" : "bg-red-500"}`} />
            <div className="text-white text-xl font-semibold">
              {connected ? "CONNECTED" : "OFFLINE"}
            </div>
          </div>

          <div className="mt-4 text-sm text-zinc-400">
            Phase: {snapshot?.phase || "UNKNOWN"}
          </div>

          <div className="mt-2 text-sm text-zinc-400">
            Sequence: {stats.lastSequence}
          </div>
        </div>

        <div className="bg-black border border-zinc-800 rounded-2xl p-5">
          <div className="text-zinc-500 text-sm">Deployments</div>

          <div className="text-white text-4xl font-bold mt-3">
            {stats.deployments}
          </div>

          <div className="mt-4 flex gap-6 text-sm">
            <div className="text-emerald-400">Success {stats.successes}</div>
            <div className="text-red-400">Fail {stats.failures}</div>
          </div>
        </div>

        <div className="bg-black border border-zinc-800 rounded-2xl p-5">
          <div className="text-zinc-500 text-sm">Replay Hashes</div>

          <div className="text-cyan-400 text-4xl font-bold mt-3">
            {stats.uniqueHashes}
          </div>

          <div className="mt-4 text-sm text-zinc-400">
            deterministic lineage active
          </div>
        </div>

        <div className="bg-black border border-zinc-800 rounded-2xl p-5">
          <div className="text-zinc-500 text-sm">Capital</div>

          <div className="text-emerald-400 text-4xl font-bold mt-3">
            ${Number(snapshot?.capital || 0).toFixed(0)}
          </div>

          <div className="mt-4 text-sm text-zinc-400">
            ROAS {Number(snapshot?.avg_roas || 0).toFixed(2)}
          </div>
        </div>
      </div>

      <DesktopWorkspace />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2">
          {/* Pre-existing broken reference removed: this imported a
              component named RuntimeGraph that never existed — only a
              type + buildRuntimeGraph() helper live in ../runtimeGraph.ts.
              Left unimplemented here rather than fabricated; a real
              graph visualization is out of scope for this pass. */}
        </div>

        <div className="space-y-6">
          <div className="bg-black border border-zinc-800 rounded-2xl p-5">
            <div className="text-white font-semibold mb-5">
              Desktop Operator Controls
            </div>

            <div className="grid grid-cols-1 gap-3">
              <button
                onClick={() => executeControl("resume", "/runner/resume")}
                disabled={busy !== null}
                className="bg-emerald-500 hover:bg-emerald-400 transition rounded-xl px-4 py-3 text-black font-semibold"
              >
                {busy === "resume" ? "Starting..." : "Resume Runtime"}
              </button>

              <button
                onClick={() => executeControl("pause", "/runner/pause")}
                disabled={busy !== null}
                className="bg-yellow-500 hover:bg-yellow-400 transition rounded-xl px-4 py-3 text-black font-semibold"
              >
                {busy === "pause" ? "Pausing..." : "Pause Runtime"}
              </button>

              <button
                onClick={() => executeControl("cycle", "/cycle")}
                disabled={busy !== null}
                className="bg-cyan-500 hover:bg-cyan-400 transition rounded-xl px-4 py-3 text-black font-semibold"
              >
                {busy === "cycle" ? "Executing..." : "Run Single Cycle"}
              </button>
            </div>
          </div>

          <div className="bg-black border border-zinc-800 rounded-2xl p-5 h-[300px]">
            <div className="text-white font-semibold mb-4">
              Runtime Throughput
            </div>

            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={chartData}>
                <XAxis dataKey="index" hide />
                <YAxis hide />
                <Tooltip />

                <Area
                  type="monotone"
                  dataKey="sequence"
                  stroke="#22d3ee"
                  fill="#083344"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <DeploymentTimeline />
        <AgentActivity />
        <InventoryOps />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <ClaudeStrategyFeed />
        <ReplayInspector />
        <OperatorQuickActions />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="bg-black border border-zinc-800 rounded-2xl p-5">
          <div className="text-white font-semibold mb-5">
            Product Intelligence
          </div>

          <div className="space-y-4">
            {stats.products.length === 0 && (
              <div className="text-zinc-500 text-sm">
                waiting for commerce telemetry
              </div>
            )}

            {stats.products.map((product) => (
              <div
                key={product.name}
                className="flex items-center justify-between border-b border-zinc-800 pb-3"
              >
                <div className="text-zinc-200">{product.name}</div>

                <div className="text-emerald-400 font-semibold">
                  {product.score.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-black border border-zinc-800 rounded-2xl p-5">
          <div className="text-white font-semibold mb-5">
            Creative Intelligence
          </div>

          <div className="space-y-4">
            {stats.creatives.length === 0 && (
              <div className="text-zinc-500 text-sm">
                waiting for creative telemetry
              </div>
            )}

            {stats.creatives.map((creative) => (
              <div
                key={creative.name}
                className="flex items-center justify-between border-b border-zinc-800 pb-3"
              >
                <div className="text-zinc-200">{creative.name}</div>

                <div className="text-cyan-400 font-semibold">
                  {creative.score.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-black border border-zinc-800 rounded-2xl p-5">
          <div className="text-white font-semibold mb-5">
            Replay Timeline
          </div>

          <div className="space-y-3 max-h-[360px] overflow-auto pr-2">
            {recentEvents.map((event, index) => (
              <div
                key={`${event.sequence_id}-${index}`}
                className="border border-zinc-800 rounded-xl p-3"
              >
                <div className="flex items-center justify-between">
                  <div className="text-cyan-400 text-sm">{event.type}</div>

                  <div className="text-zinc-500 text-xs">
                    seq {event.sequence_id || "-"}
                  </div>
                </div>

                <div className="mt-2 text-xs text-zinc-500 break-all">
                  {event.replay_hash || "no replay hash"}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
