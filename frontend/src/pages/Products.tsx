import { usePlaybook, useSnapshot } from "@/lib/api";
import { PlaybookPanel } from "@/components/PlaybookPanel";
import type { Patterns } from "@/types";

const EMPTY_PATTERNS: Patterns = {
  hook_scores: {},
  angle_scores: {},
  regime_scores: {},
  top_hooks: [],
  top_angles: [],
};

export default function Products() {
  const { data: playbookData, isLoading } = usePlaybook();
  const { data: snapshot } = useSnapshot();

  const playbooks = Array.isArray(playbookData) ? playbookData : playbookData?.playbooks ?? [];
  const patterns: Patterns = snapshot?.patterns ?? EMPTY_PATTERNS;

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-lg font-semibold text-zinc-100">Products</h1>
      {isLoading ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : (
        <PlaybookPanel playbooks={playbooks} patterns={patterns} />
      )}
    </div>
  );
}
