import { useState } from "react";
import type { PublicityScenario } from "../../marketing-publicity-surface/lib/composePublicityScenario.ts";

export function StrategyWorkbench({ scenario }: { scenario: PublicityScenario }) {
  const [exportText, setExportText] = useState<string | null>(null);
  return (
    <article className="mx-auto grid max-w-5xl gap-4 p-4 md:grid-cols-2 motion-reduce:transition-none" aria-labelledby="strategy-title">
      <a href="#strategy-claims" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4">
        Skip to claims
      </a>
      <header className="space-y-2">
        <p className="text-xs uppercase tracking-wide text-amber-300" role="status" aria-live="polite">
          Draft only · not an executed campaign
        </p>
        <h1 id="strategy-title" className="text-xl font-semibold" tabIndex={-1}>
          {scenario.title}
        </h1>
        <p>{scenario.banner}</p>
        <p>
          Offer kind: {scenario.offer_kind}. Surface: {scenario.surface}.
        </p>
      </header>

      <section aria-labelledby="audience-heading">
        <h2 id="audience-heading">Target audience and segments</h2>
        <ul>
          {scenario.audience.map((segment) => (
            <li key={segment.segment_id}>
              {segment.label}. {segment.description}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="position-heading">
        <h2 id="position-heading">Positioning and message hierarchy</h2>
        <p>{scenario.positioning}</p>
        <ol>
          {scenario.messages.map((message) => (
            <li key={message.message_id}>
              {message.level}: {message.text}
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="angles-heading">
        <h2 id="angles-heading">Offer angles</h2>
        <ul>
          {scenario.offer_angles.map((angle) => (
            <li key={angle.angle_id}>
              {angle.headline} ({angle.kind}). {angle.planning_note}
            </li>
          ))}
        </ul>
      </section>

      <section id="strategy-claims" aria-labelledby="claims-heading" className="overflow-x-auto">
        <h2 id="claims-heading">Evidence-linked claims</h2>
        <table>
          <caption>Claims without evidence stay in needs rescenario.</caption>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Review</th>
              <th scope="col">Evidence labels</th>
            </tr>
          </thead>
          <tbody>
            {scenario.claims.map((claim) => (
              <tr key={claim.claim_id} tabIndex={0}>
                <td>{claim.text}</td>
                <td>{claim.status === "needs_review" ? "Needs review" : claim.status}</td>
                <td>{claim.evidence_labels.join(", ") || "No evidence"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section aria-labelledby="obj-heading">
        <h2 id="obj-heading">Objections</h2>
        <ul>
          {scenario.objections.map((item) => (
            <li key={item.objection_id}>
              {item.text} ({item.evidence_labels.join(", ")})
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="pr-heading">
        <h2 id="pr-heading">Publicity and PR angles</h2>
        <ul>
          {scenario.publicity.map((angle) => (
            <li key={angle.angle_id}>
              {angle.outlet_type}: {angle.pitch}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="pillar-heading">
        <h2 id="pillar-heading">Organic content pillars</h2>
        <ul>
          {scenario.pillars.map((pillar) => (
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
          {scenario.paid_tests.map((cell) => (
            <li key={cell.cell_id}>
              {cell.channel}: {cell.hypothesis} ({cell.budget_assumption_label})
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="ugc-heading">
        <h2 id="ugc-heading">UGC briefs</h2>
        <ul>
          {scenario.ugc_briefs.map((brief) => (
            <li key={brief.brief_id}>{brief.prompt_for_creator}</li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="calendar-heading">
        <h2 id="calendar-heading">Content calendar</h2>
        <ul>
          {scenario.calendar.map((item) => (
            <li key={item.item_id}>
              {item.week_label} · {item.channel} · {item.draft_title}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="channel-heading">
        <h2 id="channel-heading">Channel recommendations</h2>
        <ul>
          {scenario.channels.map((channel) => (
            <li key={channel.channel_id}>
              {channel.channel}: {channel.rationale}
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="kpi-heading">
        <h2 id="kpi-heading">KPI definitions</h2>
        <ul>
          {scenario.kpis.map((kpi) => (
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
          {scenario.budgets.map((budget) => (
            <li key={budget.scenario_id}>
              {budget.name}: {budget.amount_label} (assumption)
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="measure-heading">
        <h2 id="measure-heading">Measurement plan</h2>
        <ol>
          {scenario.measurement.map((step) => (
            <li key={step.step_id}>{step.description}</li>
          ))}
        </ol>
      </section>

      <section className="md:col-span-2" aria-labelledby="rules-heading">
        <h2 id="rules-heading">Kill, iterate, and scale criteria</h2>
        <ul>
          {scenario.decision_rules.map((rule) => (
            <li key={rule.rule_id}>
              {rule.kind}: {rule.text} (assumption)
            </li>
          ))}
        </ul>
      </section>

      <section aria-labelledby="blocker-heading">
        <h2 id="blocker-heading">Legal and privacy blockers</h2>
        <ul>
          {scenario.legal_blockers.map((blocker) => (
            <li key={blocker.blocker_id}>
              {blocker.domain}: {blocker.reason}
            </li>
          ))}
        </ul>
      </section>

      <section id="human-approvals" className="md:col-span-2" aria-labelledby="next-heading">
        <h2 id="next-heading">Human approvals</h2>
        <ul>
          {scenario.approvals.map((action) => (
            <li key={action.approval_id}>
              {action.label} Granted: no.
            </li>
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
