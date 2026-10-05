import { useId } from "react";
import type { OwnerActivityState } from "../lib/ownerActivity.ts";

export function OwnerActivityPanel({
  activity,
}: {
  activity: OwnerActivityState;
}) {
  const headingId = useId();
  const freshness = activity.phase === "ready" && activity.freshnessTimestamp !== null
    ? timestampPresentation(activity.freshnessTimestamp)
    : null;
  return (
    <section
      aria-labelledby={headingId}
      className="space-y-3 rounded border border-zinc-700 bg-zinc-950 p-4 text-zinc-100"
      data-owner-activity
    >
      <header className="space-y-1">
        <h3 id={headingId} className="text-base font-semibold">
          Activity and freshness
        </h3>
        <p className="text-sm text-zinc-300">
          Read-only canonical event activity. Event identity, API order, source labels, and authority flags are preserved. The endpoint orders events oldest-first, so offset 0 is not the newest activity; freshness describes only the returned page.
        </p>
      </header>

      {activity.phase === "loading" && (
        <p role="status" aria-live="polite" className="text-sm text-zinc-300">
          Loading canonical activity.
        </p>
      )}
      {activity.phase === "empty" && (
        <p role="status" className="text-sm text-zinc-300">
          No events returned for this canonical page. Empty is not an observed zero.
        </p>
      )}
      {activity.phase === "error" && (
        <p role="alert" className="text-sm text-red-200">
          {activity.message}
        </p>
      )}
      {activity.phase === "unavailable" && (
        <p role="status" className="text-sm text-amber-200">
          Activity unavailable. {activity.message}
        </p>
      )}
      {activity.phase === "ready" && (
        <>
          <p className="text-sm text-zinc-300">
            Latest timestamp in this returned page only: {activity.freshnessTimestamp === null
              ? "not available"
              : <time dateTime={freshness?.dateTime}>{freshness?.text}</time>}
            . Page size {activity.query.limit}; offset {activity.query.offset}.
          </p>
          <p className="text-xs text-zinc-400">
            Source labels are preserved; they do not prove live validation. No event source is promoted to live evidence here.
          </p>
          {activity.warnings.length > 0 && (
            <p role="status" className="text-xs text-amber-200">
              Source warnings: {activity.warnings.join(", ")}
            </p>
          )}
          <ol aria-label="Canonical events in API order" className="divide-y divide-zinc-800">
            {activity.events.map((event) => {
              const timestamp = timestampPresentation(event.occurredAt);
              return (
                <li key={event.eventId} className="space-y-1 py-3 first:pt-0 last:pb-0">
                  <p className="font-medium">{event.eventType}</p>
                  <p className="text-xs text-zinc-300">
                    Event ID: <code>{event.eventId}</code>
                  </p>
                  <p className="text-xs text-zinc-300">
                    Occurred at: <time dateTime={timestamp.dateTime}>{timestamp.text}</time>
                  </p>
                  <p className="text-xs text-zinc-300">Source: {event.sourceLabel}</p>
                  <p className="text-xs text-zinc-400">{event.sourceQualification}</p>
                  {event.evidenceLabels.length > 0 && (
                    <p className="text-xs text-zinc-400">Evidence qualifiers: {event.evidenceLabels.join(", ")}</p>
                  )}
                  {event.authorityFlags.length > 0 && (
                    <p className="text-xs text-zinc-400">Authority flags: {event.authorityFlags.join(", ")}</p>
                  )}
                </li>
              );
            })}
          </ol>
        </>
      )}
    </section>
  );
}

function timestampPresentation(timestamp: number): { dateTime?: string; text: string } {
  const date = new Date(timestamp * 1_000);
  if (Number.isNaN(date.getTime())) return { text: String(timestamp) };
  const isoTimestamp = date.toISOString();
  const localText = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(date);
  return { dateTime: isoTimestamp, text: localText };
}
