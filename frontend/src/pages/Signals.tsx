import { useOpportunities } from "@/lib/api";
import { SignalsFeed } from "@/components/SignalsFeed";
import type { Signal } from "@/types";

export default function Signals() {
  const { data, isLoading } = useOpportunities();
  const signals: Signal[] = Array.isArray(data) ? data : data?.signals ?? [];

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-lg font-semibold text-zinc-100">Signals</h1>
      {isLoading ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : (
        <SignalsFeed signals={signals} />
      )}
    </div>
  );
}
