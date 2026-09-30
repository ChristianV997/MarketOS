import { useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { LineState, OwnerCandidate, OwnerScenario } from "../contracts/ownerDashboard";
import { moneyText, ratioText } from "../lib/format";
import { BASIS_LABELS, RATIO_LABELS, humanizeCode, scenarioLabel } from "../lib/labels";
import { NOT_AVAILABLE } from "../lib/decimal";
import { BasisChip, Chip } from "./Chips";

function pickDefault(scenarios: OwnerScenario[]): OwnerScenario {
  return scenarios.find((s) => s.name === "base") ?? scenarios[0];
}

const LINE_NOTES: Record<Exclude<LineState, "ok">, string> = {
  input_missing: "Input missing",
  depends_on_missing: "Depends on missing inputs",
  excludes_missing: "Excludes a missing input",
};

function Headline({ label, value, basis, note }: { label: string; value: string; basis?: ReactNode; note?: string }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-2.5">
      <dt className="text-[11px] text-zinc-400">{label}</dt>
      <dd className="mt-0.5 break-words text-sm font-semibold text-zinc-100">{value}</dd>
      {basis ? <dd className="mt-1">{basis}</dd> : null}
      {note ? <dd className="mt-1 text-[11px] text-zinc-400">{note}</dd> : null}
    </div>
  );
}

function ScenarioBody({ scenario }: { scenario: OwnerScenario }) {
  if (scenario.status === "unavailable") {
    return (
      <div className="space-y-1 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-sm text-zinc-300">
        <p>
          <strong className="font-semibold">{NOT_AVAILABLE}.</strong> The provider could not calculate this scenario, so
          no figure is shown, not even zero.
        </p>
        {scenario.missingInputs.length > 0 ? (
          <p className="text-xs text-zinc-400">
            Missing inputs: {scenario.missingInputs.map(humanizeCode).join(", ")}.
          </p>
        ) : null}
      </div>
    );
  }
  const moneyHeadline = (key: string) => {
    const found = scenario.lines.find((l) => l.key === key);
    return (
      <Headline
        label={found?.label ?? humanizeCode(key)}
        value={found ? moneyText(found.money) : NOT_AVAILABLE}
        basis={found && found.money.kind === "amount" ? <BasisChip basis={found.money.basis} /> : undefined}
        note={found && found.state !== "ok" ? LINE_NOTES[found.state] : undefined}
      />
    );
  };
  const ratioNote = scenario.incomplete ? LINE_NOTES.depends_on_missing : undefined;
  return (
    <div className="space-y-3">
      {scenario.incomplete ? (
        <p role="note" className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-2.5 text-xs text-amber-100">
          <strong className="font-semibold">Incomplete inputs.</strong> The provider lists these as missing:{" "}
          {scenario.missingInputs.map(humanizeCode).join(", ")}. Lines for them show “{NOT_AVAILABLE}”, and totals that
          would include them are not shown, because a zero the provider fills in for a missing input is a placeholder,
          not a value.
        </p>
      ) : null}
      <dl className="grid grid-cols-[repeat(auto-fit,minmax(min(8.5rem,100%),1fr))] gap-2">
        {moneyHeadline("contribution_after_cac")}
        <Headline
          label={RATIO_LABELS.contribution_margin_after_cac}
          value={ratioText(scenario.ratios.contribution_margin_after_cac, "percent")}
          note={ratioNote}
        />
        <Headline label={RATIO_LABELS.break_even_roas} value={ratioText(scenario.ratios.break_even_roas, "multiple")} note={ratioNote} />
        {moneyHeadline("cash_required_per_order")}
      </dl>
      <div role="region" aria-label="Economics line items" tabIndex={0} className="overflow-x-auto rounded-lg border border-white/[0.06]">
        <table className="w-full min-w-[22rem] text-sm">
          <caption className="sr-only">Per-order economics line items for the {scenarioLabel(scenario.name)} scenario</caption>
          <thead className="border-b border-white/[0.06]">
            <tr>
              <th scope="col" className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-zinc-400">Line item</th>
              <th scope="col" className="px-3 py-2 text-right text-[11px] font-medium uppercase tracking-wide text-zinc-400">Amount</th>
              <th scope="col" className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wide text-zinc-400">Basis</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.04]">
            {scenario.lines.map((item) => (
              <tr key={item.key} className={cn(item.money.kind === "amount" && item.money.basis === "assumed" && "bg-amber-500/[0.04]")}>
                <th scope="row" className="px-3 py-1.5 text-left font-normal text-zinc-300">{item.label}</th>
                <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-zinc-100">{moneyText(item.money)}</td>
                <td className="px-3 py-1.5">
                  {item.money.kind === "amount" ? (
                    <span className="flex flex-wrap items-center gap-1.5">
                      <BasisChip basis={item.money.basis} />
                      {item.state === "excludes_missing" ? <Chip tone="caution">{LINE_NOTES.excludes_missing}</Chip> : null}
                    </span>
                  ) : (
                    <span className="text-xs text-zinc-400">{item.state === "ok" ? NOT_AVAILABLE : LINE_NOTES[item.state]}</span>
                  )}
                </td>
              </tr>
            ))}
            {(["contribution_margin", "contribution_margin_after_cac", "break_even_roas", "target_roas"] as const)
              .filter((key) => key in scenario.ratios)
              .map((key) => (
                <tr key={key}>
                  <th scope="row" className="px-3 py-1.5 text-left font-normal text-zinc-300">{RATIO_LABELS[key]}</th>
                  <td className="whitespace-nowrap px-3 py-1.5 text-right tabular-nums text-zinc-100">
                    {ratioText(scenario.ratios[key], key.endsWith("roas") ? "multiple" : "percent")}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-zinc-400">
                    {scenario.incomplete ? LINE_NOTES.depends_on_missing : BASIS_LABELS.derived}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function EconomicsPanel({ candidate }: { candidate: OwnerCandidate }) {
  const scenarios = candidate.scenarios;
  const [chosen, setChosen] = useState<string | null>(null);
  const current = scenarios.length === 0 ? null : (scenarios.find((s) => s.name === chosen) ?? pickDefault(scenarios));

  return (
    <section aria-labelledby={`economics-${candidate.candidateId}`} className="space-y-3">
      <h3 id={`economics-${candidate.candidateId}`} className="text-sm font-semibold text-zinc-100">
        Economics (planning estimates)
      </h3>
      <p className="text-xs text-zinc-400">
        Per-order figures the economics kernel derived from supplied inputs and assumptions. They are not measured
        results, and this page displays them exactly as provided without recalculating anything.
      </p>
      {current === null ? (
        <p className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3 text-sm text-zinc-300">
          <strong className="font-semibold">{NOT_AVAILABLE}.</strong> The provider returned no economics scenarios for
          this candidate
          {candidate.economicsMissingInputs.length > 0
            ? ` (missing inputs: ${candidate.economicsMissingInputs.map(humanizeCode).join(", ")})`
            : ""}
          .
        </p>
      ) : (
        <>
          {scenarios.length > 1 ? (
            <fieldset className="flex flex-wrap gap-2">
              <legend className="sr-only">Economics scenario</legend>
              {scenarios.map((scenario) => {
                const active = scenario.name === current.name;
                return (
                  <label
                    key={scenario.name}
                    className={cn(
                      "cursor-pointer rounded-md border px-2.5 py-1 text-xs font-medium focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-indigo-400",
                      active ? "border-indigo-400/50 bg-indigo-400/10 text-indigo-100" : "border-white/10 text-zinc-300 hover:bg-white/[0.04]",
                    )}
                  >
                    <input
                      type="radio"
                      name={`scenario-${candidate.candidateId}`}
                      value={scenario.name}
                      checked={active}
                      onChange={() => setChosen(scenario.name)}
                      className="sr-only"
                    />
                    {scenarioLabel(scenario.name)}
                    {scenario.status === "unavailable" ? " (not available)" : ""}
                  </label>
                );
              })}
            </fieldset>
          ) : null}
          <ScenarioBody scenario={current} />
          <p className="text-[11px] text-zinc-400">
            Basis: <em>Assumption</em> is an input or default, not a measurement; <em>Manual input</em> was entered by
            an operator; <em>Derived</em> was computed from other lines. Assumption rows are tinted and labelled.
          </p>
        </>
      )}
    </section>
  );
}
