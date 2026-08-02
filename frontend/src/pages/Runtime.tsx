import { useRuntimeTasks } from "@/lib/api";
import { TaskInventoryPanel } from "@/components/TaskInventoryPanel";
import type { TaskInventory } from "@/types";

export default function Runtime() {
  const { data, isLoading } = useRuntimeTasks();
  const inventory: TaskInventory | null = data ?? null;

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-4">
      <h1 className="text-lg font-semibold text-zinc-100">Runtime</h1>
      {isLoading ? (
        <p className="text-sm text-zinc-500">Loading…</p>
      ) : (
        <TaskInventoryPanel inventory={inventory} />
      )}
    </div>
  );
}
