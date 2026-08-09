# Sales automation module (`services.sales_automation`)

Chat-based lead qualification and appointment handoff. Qualification remains
local and deterministic. An optional, explicitly gated Chatwoot path records
a contact, conversation, transcript, and human-review draft; it never sends a
real customer message autonomously.

## Why qualification is simulation-only

Real outbound messaging is a distinct, higher-risk capability (rate limits,
opt-in/consent law, platform ToS, cost per message) that deserves its own
adapter-plus-live-mode-gate design — the same pattern this repo already
uses for ad platforms (`backend/integrations/tiktok_ads.py`,
`meta_ads_client.py`) and checkout (`backend/commerce/checkout.py`). Building
that prematurely, before the qualification logic itself is proven, would
mean debugging both at once. The current real path deliberately stops at
record-keeping and a draft for human approval. Sending remains outside this
module.

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
10. **Optional Chatwoot handoff** — pass `attempt_real_handoff=True` with a
    non-dry workspace and configured/allowed Chatwoot credentials. The path
    carries workspace/run lineage and an idempotency key, degrades each
    external operation independently, and only calls `handoff_to_human` when
    the existing qualification state already set `session.handed_off`.

## Try it

```bash
python -m marketos.cli services sales-bot-sim --vertical car_sales
python -m marketos.cli services sales-bot-sim --vertical real_estate \
    --message "I'm looking to buy a house in Austin" \
    --message "asap, budget is $500,000"
# Explicit opt-in; still draft-only and requires configured Chatwoot scope.
python -m marketos.cli services sales-bot-sim --vertical car_sales \
    --attempt-real-handoff --json
```

## Explicitly out of scope (future work)

- Real WhatsApp/web-chat/CRM/calendar adapters and autonomous message sending.
  Chatwoot record-keeping is the only optional real path currently supported,
  and it remains draft-only behind an explicit live gate.
- LLM-generated (vs. templated) bot replies — deliberately deterministic
  for now, matching this repo's "Deterministic First" principle; an LLM
  could later be wired in for FAQ answering specifically via the existing
  `backend/inference/router.py` (already Ollama-first, zero marginal cost
  when using a local model), but always constrained to answer only from
  supplied context, never to freelance new claims.
- Performance-bonus billing per qualified appointment (mentioned in the
  original pricing brief) — requires real booking/CRM integration first.
