import { ReplayInspector } from "@/components/ReplayInspector";

export default function Replay() {
  return (
    <div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-lg font-semibold text-zinc-100">Replay</h1>
      <ReplayInspector />
    </div>
  );
}
