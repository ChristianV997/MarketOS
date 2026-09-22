import { useState } from "react";
import type { PublicityScenario } from "../lib/composePublicityScenario.ts";

export function PublicitySurface({ scenario }: { scenario: PublicityScenario }) {
  const [preview, setPreview] = useState(false);
  return (
    <div className="mx-auto grid max-w-6xl gap-4 p-3 md:grid-cols-2 md:p-6 motion-reduce:transition-none">
      <a className="sr-only focus:not-sr-only md:col-span-2" href="#human-approvals">
        Skip to human approvals
      </a>
      <header className="md:col-span-2 space-y-2">
        <p role="status" aria-live="polite">
          Draft planning surface. Not proof. Not an executed campaign.
        </p>
        <h1 tabIndex={-1}>{scenario.title}</h1>
        <p>{scenario.banner}</p>
      </header>
      <section aria-labelledby="icp-h">
        <h2 id="icp-h">ICP and segments</h2>
        <ul>
          {scenario.audience.map((segment) => (
            <li key={segment.segment_id}>{segment.label}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="pos-h">
        <h2 id="pos-h">Positioning and message hierarchy</h2>
        <p>{scenario.positioning}</p>
        <ol>
          {scenario.messages.map((message) => (
            <li key={message.message_id}>
              {message.level}: {message.text}
            </li>
          ))}
        </ol>
      </section>
      <section className="overflow-x-auto md:col-span-2" aria-labelledby="claims-h">
        <h2 id="claims-h">Evidence-linked claims</h2>
        <table>
          <caption>Provenance stays on the packet. Labels are not proof.</caption>
          <thead>
            <tr>
              <th scope="col">Claim</th>
              <th scope="col">Status</th>
              <th scope="col">Evidence class labels</th>
              <th scope="col">Provenance</th>
            </tr>
          </thead>
          <tbody>
            {scenario.claims.map((claim) => (
              <tr key={claim.claim_id} tabIndex={0}>
                <td>{claim.text}</td>
                <td>{claim.status === "needs_review" ? "Needs review" : claim.status}</td>
                <td>{claim.evidence_labels.join(", ") || "No evidence"}</td>
                <td>{claim.provenance}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
      <section aria-labelledby="obj-h">
        <h2 id="obj-h">Objections</h2>
        <ul>
          {scenario.objections.map((item) => (
            <li key={item.objection_id}>
              {item.text} ({item.evidence_labels.join(", ")})
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="pr-h">
        <h2 id="pr-h">Publicity angles</h2>
        <ul>
          {scenario.publicity.map((item) => (
            <li key={item.angle_id}>{item.pitch}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="org-h">
        <h2 id="org-h">Organic content pillars</h2>
        <ul>
          {scenario.pillars.map((item) => (
            <li key={item.pillar_id}>{item.name}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="paid-h">
        <h2 id="paid-h">Paid-test hypotheses</h2>
        <p>Planning only. No ad spend control.</p>
        <ul>
          {scenario.paid_tests.map((item) => (
            <li key={item.cell_id}>{item.hypothesis}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="ugc-h">
        <h2 id="ugc-h">UGC briefs</h2>
        <ul>
          {scenario.ugc_briefs.map((item) => (
            <li key={item.brief_id}>{item.prompt_for_creator}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="cal-h">
        <h2 id="cal-h">Content calendar</h2>
        <ul>
          {scenario.calendar.map((item) => (
            <li key={item.item_id}>{item.draft_title}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="ch-h">
        <h2 id="ch-h">Channels</h2>
        <ul>
          {scenario.channels.map((item) => (
            <li key={item.channel_id}>{item.channel}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="funnel-h">
        <h2 id="funnel-h">Funnel and landing-page assumptions</h2>
        <ul>
          {scenario.funnel.map((item) => (
            <li key={item.step_id}>{item.label} (assumption)</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="kpi-h">
        <h2 id="kpi-h">KPI definitions</h2>
        <ul>
          {scenario.kpis.map((item) => (
            <li key={item.kpi_id}>{item.name}</li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="budget-h">
        <h2 id="budget-h">Planning budgets</h2>
        <ul>
          {scenario.budgets.map((item) => (
            <li key={item.scenario_id}>
              {item.name}: {item.amount_label} (assumption)
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="measure-h">
        <h2 id="measure-h">Measurement</h2>
        <ol>
          {scenario.measurement.map((item) => (
            <li key={item.step_id}>{item.description}</li>
          ))}
        </ol>
      </section>
      <section aria-labelledby="rules-h">
        <h2 id="rules-h">Kill, iterate, and scale criteria</h2>
        <ul>
          {scenario.decision_rules.map((item) => (
            <li key={item.rule_id}>
              {item.kind}: {item.text} (assumption)
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="legal-h">
        <h2 id="legal-h">Legal and privacy blockers</h2>
        <ul>
          {scenario.legal_blockers.map((item) => (
            <li key={item.blocker_id}>
              {item.domain}: {item.reason}
            </li>
          ))}
        </ul>
      </section>
      <section id="human-approvals" className="md:col-span-2" aria-labelledby="approve-h">
        <h2 id="approve-h">Human approvals</h2>
        <ul>
          {scenario.approvals.map((item) => (
            <li key={item.approval_id}>
              {item.label} Granted: {item.granted ? "yes" : "no"}.
            </li>
          ))}
        </ul>
        <button type="button" onClick={() => setPreview(true)}>
          Show client-safe export status
        </button>
        {preview ? (
          <p role="region" aria-label="Export status">
            Export {scenario.export_ok ? "accepted as a draft preview" : "rejected"}. Research{" "}
            {scenario.research.ok ? "checked" : "unavailable"}. Launch remains unauthorized.
          </p>
        ) : null}
      </section>
    </div>
  );
}
