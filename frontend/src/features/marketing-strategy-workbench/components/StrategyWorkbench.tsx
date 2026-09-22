import { useState } from "react";
import type { StrategyView } from "../lib/composeStrategyView.ts";

export function StrategyWorkbench({ view }: { view: StrategyView }) {
  const [exportText, setExportText] = useState<string | null>(null);
  return (
    <article className="mx-auto flex max-w-5xl flex-col gap-4 p-4 motion-reduce:transition-none" aria-labelledby="strategy-title">
      <a href="#strategy-claims" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4">
        Skip to claims
      </a>
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-amber-300" role="status" aria-live="polite">
          Draft only · not an executed campaign
        </p>
        <h1 id="strategy-title" className="text-xl font-semibold" tabIndex={-1}>
          {view.title}
        </h1>
        <p>{view.banner}</p>
        <p>
          Offer kind: {view.offer_kind}. Surface: {view.surface}.
        </p>
      </header>

      <section aria-labelledby="audience-heading">
        <h2 id="audience-heading">Target audience and segments</h2>
        <ul>
          {view.audience.map((segment) => (
            <li key={segment.segment_id}>
              {segment.label}. {segment.description}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="position-heading">
        <h2 id="position-heading">Positioning and message hierarchy</h2>
        <p>{view.positioning}</p>
        <ol>
          {view.messages.map((message) => (
            <li key={message.message_id}>
              {message.level}: {message.text}
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="angles-heading">
        <h2 id="angles-heading">Offer angles</h2>
        <ul>
          {view.offer_angles.map((angle) => (
            <li key={angle.angle_id}>
              {angle.headline} ({angle.kind}). {angle.planning_note}
            </li>
          ))}
        </ul>
      </section>

      <section id="strategy-claims" aria-labelledby="claims-heading" className="overflow-x-auto">
        <h2 id="claims-heading">Evidence-linked claims</h2>
        <table>
          <caption>Claims without evidence stay in needs review.</caption>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Review</th>
              <th scope="col">Evidence labels</th>
            </tr>
          </thead>
          <tbody>
            {view.claims.map((claim) => (
              <tr key={claim.claim_id} tabIndex={0}>
                <td>{claim.text}</td>
                <td>{claim.status === "needs_review" ? "Needs review" : claim.status}</td>
                <td>{claim.evidence_labels.join(", ") || "No evidence"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-labelledby="pr-heading">
        <h2 id="pr-heading">Publicity and PR angles</h2>
        <ul>
          {view.publicity.map((angle) => (
            <li key={angle.angle_id}>
              {angle.outlet_type}: {angle.pitch}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="pillar-heading">
        <h2 id="pillar-heading">Organic content pillars</h2>
        <ul>
          {view.pillars.map((pillar) => (
            <li key={pillar.pillar_id}>
              {pillar.name}. {pillar.intent}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="paid-heading">
        <h2 id="paid-heading">Paid test matrix</h2>
        <p>Planning cells only. No spend control.</p>
        <ul>
          {view.paid_tests.map((cell) => (
            <li key={cell.cell_id}>
              {cell.channel}: {cell.hypothesis} ({cell.budget_assumption_label})
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="ugc-heading">
        <h2 id="ugc-heading">UGC briefs</h2>
        <ul>
          {view.ugc_briefs.map((brief) => (
            <li key={brief.brief_id}>{brief.prompt_for_creator}</li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="calendar-heading">
        <h2 id="calendar-heading">Content calendar</h2>
        <ul>
          {view.calendar.map((item) => (
            <li key={item.item_id}>
              {item.week_label} · {item.channel} · {item.draft_title}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="channel-heading">
        <h2 id="channel-heading">Channel recommendations</h2>
        <ul>
          {view.channels.map((channel) => (
            <li key={channel.channel_id}>
              {channel.channel}: {channel.rationale}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading">KPI definitions</h2>
        <ul>
          {view.kpis.map((kpi) => (
            <li key={kpi.kpi_id}>
              {kpi.name}: {kpi.definition}
              {kpi.assumption ? " (assumption)" : ""}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="budget-heading">
        <h2 id="budget-heading">Budget scenarios</h2>
        <p>Every amount below is a planning assumption, not an authorization to spend.</p>
        <ul>
          {view.budgets.map((budget) => (
            <li key={budget.scenario_id}>
              {budget.name}: {budget.amount_label} (assumption)
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="measure-heading">
        <h2 id="measure-heading">Measurement plan</h2>
        <ol>
          {view.measurement.map((step) => (
            <li key={step.step_id}>{step.description}</li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="blocker-heading">
        <h2 id="blocker-heading">Approval blockers</h2>
        <ul>
          {view.blockers.map((blocker) => (
            <li key={blocker.blocker_id}>{blocker.reason}</li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="next-heading">
        <h2 id="next-heading">Next actions</h2>
        <ul>
          {view.next_actions.map((action) => (
            <li key={action.action_id}>{action.label} Human review required.</li>
          ))}
        </ul>
        <button
          type="button"
          onClick={() =>
            setExportText(
              "Client-safe preview stays in this page. It does not post, fund, or message anyone.",
            )
          }
        >
          Show bounded export preview
        </button>
        {exportText ? <p role="region" aria-label="Export preview">{exportText}</p> : null}
      </section>
    </article>
  );
}
