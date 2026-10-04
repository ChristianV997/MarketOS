import type { StepId } from "../contracts/clientProfileDraft.ts";

const NOTE: Partial<Record<StepId, string>> = {
  audience: "Segments and target markets are saved to the server. Categories stay in this tab only.",
  offerings: "Only the offering names are saved to the server. Descriptions, delivery, availability, SKU and units stay in this tab only.",
  social: "Only the platform and handle are saved to the server. Links and notes stay in this tab only, and an account without a handle is not saved.",
};

/** Live mode only: says, before anything is typed, which fields on this step the server will keep. */
export function TabOnlyNote({ step }: { step: StepId }) {
  const text = NOTE[step];
  return text ? (
    <p role="note" data-tab-only-note className="rounded border border-zinc-600 bg-zinc-900/60 p-3 text-sm text-zinc-200">
      {text}
    </p>
  ) : null;
}
