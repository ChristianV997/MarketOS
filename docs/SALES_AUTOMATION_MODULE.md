# Sales automation module (`services.sales_automation`)

Chat-based lead qualification and appointment handoff. **The qualification
logic itself is simulation-only** — every function still operates on
in-memory `ChatSession` objects, and no real message is ever sent to a real
lead. Conversation/CRM record-keeping now has an optional, explicitly-gated
**real, draft-only** path via Chatwoot (see "Real conversation handoff"
below) — WhatsApp, web chat, CRM, and calendar adapters remain unwired.

## Why simulation-only

Real outbound messaging is a distinct, higher-risk capability (rate limits,
opt-in/consent law, platform ToS, cost per message) that deserves its own
adapter-plus-live-mode-gate design — the same pattern this repo already
uses for ad platforms (`backend/integrations/tiktok_ads.py`,
`meta_ads_client.py`) and checkout (`backend/commerce/checkout.py`). Building
that prematurely, before the qualification logic itself is proven, would
mean debugging both at once. This phase deliberately stops at "prove the
qualification logic and appointment scoring work," leaving the messaging
adapter as clearly-scoped future work.

## How it works

1. **`generate_qualification_flow(vertical)`** — reuses
   `services.customer_intelligence.vertical_playbooks` (all 7 verticals)
   for the high-level question set; falls back to 5 generic slots
   (intent/need/timeline/budget/location) for an unknown vertical.
2. **`qualify_lead(slots, message)`** — deterministic keyword/regex
   extraction (intent keywords, timeline keywords, a currency-amount
   regex, a simple location-hint regex). No LLM call, no network, no cost,
   fully unit-testable offline. First-write-wins per slot — a lead's
   answer isn't silently overwritten by an ambiguous later message.
3. **`handle_chat_turn(session, message)`** — the state machine: records
   the turn, updates slots, recomputes confidence (`filled_slots / 5`),
   decides whether to hand off, and records the bot's next reply.
4. **Hand-off triggers** (any one of):
   - intent is `support` (a complaint/problem) — routed to a human
     immediately, never auto-resolved by the bot.
   - confidence stays below 0.4 after 6+ lead turns — the bot doesn't
     keep guessing indefinitely.
   - all 5 slots are filled — fully qualified, ready to book.
5. **`answer_faq(question, context)`** — keyword-overlap match against an
   operator-supplied FAQ dict. No match → an honest "I don't have that
   information" message, never a fabricated answer. This is the concrete
   mechanism behind "avoid making unsupported claims."
6. **No binding commitments**: every bot message template is deliberately
   non-committal on price, availability, and timelines — those are always
   framed as something a human confirms next, not something the bot promises.
7. **`create_appointment_handoff(session)`** — a lead-quality score (0-1,
   weighted by slot completeness + intent + urgency) and a recommended
   action (`book_appointment` vs `human_qualification_needed`), plus a
   transcript summary built only from what the lead actually said.
8. **`generate_follow_up_sequence(session)`** — 3 template re-engagement
   messages for a cold lead; references captured slots only when they were
   actually captured, never invents specifics.
9. **`run_sales_bot_simulation(vertical, scripted_lead_messages)`** — the
   local simulation harness: drives a full scripted conversation and
   produces a `CommercialRunEnvelope`-backed result, same as every other
   service module in this repo (audit trail, ArtifactStore persistence).

## Try it

```bash
python -m marketos.cli services sales-bot-sim --vertical car_sales
python -m marketos.cli services sales-bot-sim --vertical real_estate \
    --message "I'm looking to buy a house in Austin" \
    --message "asap, budget is $500,000"
```

## Real conversation handoff (`real_handoff.py`, optional)

`attempt_real_conversation_handoff` bridges a completed simulation to
`backend.contracts.adapters.ConversationProvider`
(`backend/integrations/chatwoot.py`'s `conversation_provider_chatwoot`) —
but only when explicitly asked to. It is a no-op (returns `None`) unless
**all** of the following hold:

1. The caller passed `attempt_real_handoff=True` (CLI:
   `--attempt-real-handoff`; API: `attempt_real_handoff` body param).
2. `workspace.dry_run_default` is `False`.
3. `backend.workspaces.credential_scope.scope_for(workspace)` reports
   Chatwoot as `configured`, non-dry-run, and allowed.

This mirrors the existing `confirm_live` precedent in `backend/api.py` and
the `live_action_requested` flag in
`services/ecommerce_operator/launch_guard.py` — a real attempt always
requires an explicit opt-in on top of a live workspace, never an implicit
one. It deliberately does not reuse
`backend.workspaces.live_mode_checklist.check()`, since that gate is
spend/budget-ceiling-shaped and would wrongly block a non-monetary
conversation action.

When the gate is open, it creates a Chatwoot contact and conversation,
backfills the lead's transcript, and stages a draft reply — `draft`, per
`ConversationProvider`'s own contract, is always
`draft_pending_human_approval`; this module never gains a live-send path.
It only calls `handoff_to_human` when `session.handed_off` is already
`True` from `appointment_flow.py`'s existing decision logic — it never
makes a second, independent handoff decision. Every provider call is
independently try/excepted, so one failure never aborts the rest.

Default calls (`attempt_real_handoff` omitted or `False`) are unaffected —
`run_sales_bot_simulation`'s 4-tuple return stays byte-identical; the real
handoff result and a `status` label (via `services.status.commercial_status`)
live in `envelope.outputs`, not in the return tuple.

## Explicitly out of scope (future work)

- Real WhatsApp/web-chat/calendar adapters, and a CRM adapter (see
  `docs/CRM_CANDIDATE_RESEARCH.md` for research on permissively-licensed
  candidates) — the live-mode gate pattern above is designed to extend to
  those the same way once they exist.
- LLM-generated (vs. templated) bot replies — deliberately deterministic
  for now, matching this repo's "Deterministic First" principle; an LLM
  could later be wired in for FAQ answering specifically via the existing
  `backend/inference/router.py` (already Ollama-first, zero marginal cost
  when using a local model), but always constrained to answer only from
  supplied context, never to freelance new claims.
- Performance-bonus billing per qualified appointment (mentioned in the
  original pricing brief) — requires real booking/CRM integration first.
