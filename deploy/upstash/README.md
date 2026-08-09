# Upstash evaluation target

Upstash Redis/QStash may replace self-managed lightweight queues and scheduled
HTTP jobs after the manual public-signal workflow has proved useful. The MVP
Island does not enqueue, schedule, or retry jobs. Any future QStash endpoint
must be authenticated, idempotent, dry-run by default, rate bounded, and human
reviewable before it can affect downstream planning.
