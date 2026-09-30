import { RefreshCw } from "lucide-react";
import type { OwnerDashboardViewModel } from "../contracts/ownerDashboard";

export function LoadingState() {
  return (
    <div role="status" aria-busy="true" aria-live="polite" className="space-y-4">
      <p className="text-sm text-zinc-400">Loading owner dashboard…</p>
      <div aria-hidden="true" className="grid grid-cols-[repeat(auto-fit,minmax(min(9.5rem,100%),1fr))] gap-3">
        {Array.from({ length: 5 }, (_, index) => (
          <div key={index} className="h-20 animate-pulse rounded-xl border border-white/[0.06] bg-white/[0.03]" />
        ))}
      </div>
      <div aria-hidden="true" className="h-64 animate-pulse rounded-xl border border-white/[0.06] bg-white/[0.03]" />
    </div>
  );
}

export function ErrorState({
  error,
  heading,
  onRetry,
  isRetrying,
}: {
  error: NonNullable<OwnerDashboardViewModel["error"]>;
  heading: string;
  onRetry: () => void;
  isRetrying: boolean;
}) {
  return (
    <div role="alert" className="space-y-3 rounded-xl border border-rose-500/30 bg-rose-500/5 p-5">
      <h2 className="text-base font-semibold text-rose-100">{heading}</h2>
      <p className="text-sm text-zinc-300">{error.message}</p>
      <p className="text-xs text-zinc-400">
        Reason code: <code className="text-zinc-300">{error.code}</code>
      </p>
      <button
        type="button"
        onClick={onRetry}
        disabled={isRetrying}
        className="inline-flex items-center gap-2 rounded-md border border-white/10 bg-white/[0.06] px-3 py-1.5 text-sm font-medium text-zinc-100 hover:bg-white/10 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <RefreshCw aria-hidden="true" className={isRetrying ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
        {isRetrying ? "Trying again…" : "Try again"}
      </button>
    </div>
  );
}

export function EmptyState({ run }: { run: OwnerDashboardViewModel["run"] }) {
  return (
    <div className="space-y-2 rounded-xl border border-white/[0.06] bg-white/[0.02] p-5">
      <h2 className="text-base font-semibold text-zinc-100">No opportunities yet</h2>
      <p className="text-sm text-zinc-400">
        The discovery run returned no candidates. Discovery only evaluates candidates you supply evidence for; it never
        invents a category, market, or product.
      </p>
      {run?.nextBestAction ? (
        <p className="text-sm text-zinc-300">
          <span className="text-zinc-400">Provider next step:</span> {run.nextBestAction}
        </p>
      ) : null}
    </div>
  );
}
