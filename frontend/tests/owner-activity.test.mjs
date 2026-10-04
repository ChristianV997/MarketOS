import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import Module from "node:module";
import React from "react";
import ReactDOMServer from "react-dom/server";
import test from "node:test";
import ts from "typescript";
import {
  OWNER_ACTIVITY_QUERY,
  OWNER_ACTIVITY_UNAVAILABLE,
  presentCanonicalEventResponse,
} from "../src/features/owner-performance/lib/ownerActivity.ts";

async function loadOwnerActivityPanel() {
  const componentPath = fileURLToPath(
    new URL("../src/features/owner-performance/components/OwnerActivityPanel.tsx", import.meta.url)
  );
  const source = await readFile(componentPath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
  });
  const loaded = new Module(componentPath);
  loaded.filename = componentPath;
  loaded.paths = Module._nodeModulePaths(dirname(componentPath));
  loaded._compile(compiled.outputText, componentPath);
  return loaded.exports.OwnerActivityPanel;
}

const OwnerActivityPanel = await loadOwnerActivityPanel();

const response = {
  timeline: {
    workspace_id: "workspace-owner",
    events: [
      {
        event_id: "event-old",
        event_type: "manual_quote_imported",
        occurred_at: 1_800_000_000,
        source: "manual",
        dry_run: true,
        advisory: true,
        read_only: true,
        authority_flags: ["non_authoritative"],
      },
      {
        event_id: "event-new",
        event_type: "fixture_replay_completed",
        occurred_at: 1_800_000_100,
        source: "fixture",
        dry_run: false,
        advisory: true,
        read_only: true,
        authority_flags: [],
      },
    ],
    event_type_counts: {},
    aggregate_type_counts: {},
    first_occurred_at: 1_800_000_000,
    last_occurred_at: 1_800_000_100,
    warnings: [],
  },
};

function render(activity) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(OwnerActivityPanel, { activity })
  );
}

test("activity adapter fixes a bounded limit/offset request without cursor semantics", () => {
  assert.deepEqual(OWNER_ACTIVITY_QUERY, { limit: 10, offset: 0 });
  assert.equal("cursor" in OWNER_ACTIVITY_QUERY, false);
});

test("activity adapter preserves canonical identity, returned order, source and authority flags", () => {
  const activity = presentCanonicalEventResponse(response);
  assert.equal(activity.phase, "ready");
  assert.deepEqual(activity.events.map((event) => event.eventId), ["event-old", "event-new"]);
  assert.deepEqual(activity.events.map((event) => event.sourceLabel), ["manual", "fixture"]);
  assert.deepEqual(activity.events[0].evidenceLabels, ["Dry run", "Advisory", "Read only"]);
  assert.deepEqual(activity.events[0].authorityFlags, ["non_authoritative"]);
  assert.equal(activity.freshnessTimestamp, 1_800_000_100);
  assert.deepEqual(activity.query, OWNER_ACTIVITY_QUERY);
});

test("activity adapter preserves the supplied limit/offset query", () => {
  const query = { limit: 5, offset: 20 };
  const activity = presentCanonicalEventResponse(response, query);
  assert.deepEqual(activity.query, query);
});

test("malformed canonical event responses become an explicit accessible error state", () => {
  const activity = presentCanonicalEventResponse({ timeline: { events: [null], warnings: [] } });
  assert.equal(activity.phase, "error");
  assert.match(activity.message, /missing its identity/i);
  assert.match(render(activity), /role="alert"/);
});

test("malformed source warnings fail closed instead of masquerading as an empty page", () => {
  for (const warnings of [undefined, ["valid", 7]]) {
    const activity = presentCanonicalEventResponse({
      timeline: { ...response.timeline, events: [], warnings },
    });
    assert.equal(activity.phase, "error");
    assert.match(activity.message, /warnings are invalid/i);
  }
});

test("duplicate event IDs fail closed instead of creating ambiguous rendered rows", () => {
  const duplicateIdResponse = {
    timeline: {
      ...response.timeline,
      events: [response.timeline.events[0], { ...response.timeline.events[1], event_id: "event-old" }],
    },
  };
  const activity = presentCanonicalEventResponse(duplicateIdResponse);
  assert.equal(activity.phase, "error");
  assert.match(activity.message, /duplicate event identities/i);
});

test("unconfigured canonical source is unavailable rather than a successful empty result", () => {
  const activity = presentCanonicalEventResponse({
    timeline: { ...response.timeline, events: [], warnings: ["jsonl_read_path_unconfigured"] },
  });
  assert.equal(activity.phase, "unavailable");
  assert.match(activity.message, /source is not configured/i);
});

test("a configured page with no events is explicitly empty", () => {
  const activity = presentCanonicalEventResponse({
    timeline: { ...response.timeline, events: [], warnings: [] },
  });
  assert.equal(activity.phase, "empty");
});

test("unavailable panel explains owner-scope limitation and makes no live claim", () => {
  const html = render(OWNER_ACTIVITY_UNAVAILABLE);
  assert.match(html, /Activity and freshness/);
  assert.match(html, /oldest-first/);
  assert.match(html, /verified owner workspace/i);
  assert.match(html, /does not request/i);
  assert.match(html, /role="status"/);
});

test("panel heading identifiers remain unique when multiple panels are rendered", () => {
  const tree = React.createElement(
    "div",
    null,
    React.createElement(OwnerActivityPanel, { activity: OWNER_ACTIVITY_UNAVAILABLE }),
    React.createElement(OwnerActivityPanel, { activity: OWNER_ACTIVITY_UNAVAILABLE })
  );
  const html = ReactDOMServer.renderToStaticMarkup(tree);
  const headingIds = [...html.matchAll(/aria-labelledby="([^"]+)"/g)].map((match) => match[1]);
  assert.equal(headingIds.length, 2);
  assert.equal(new Set(headingIds).size, 2);
});

test("loading, empty and error panels expose accessible state announcements", () => {
  const loading = render({ phase: "loading" });
  const empty = render({ phase: "empty" });
  const error = render({ phase: "error", message: "Canonical event read failed." });
  assert.match(loading, /role="status"/);
  assert.match(loading, /aria-live="polite"/);
  assert.match(empty, /No events returned/);
  assert.match(empty, /not an observed zero/);
  assert.match(error, /role="alert"/);
  assert.match(error, /Canonical event read failed/);
});

test("ready panel preserves API order and labels manual and fixture sources without calling them live", () => {
  const html = render(presentCanonicalEventResponse(response));
  assert.ok(html.indexOf("event-old") < html.indexOf("event-new"));
  assert.match(html, /Source: manual/);
  assert.match(html, /Source: fixture/);
  assert.match(html, /Manual evidence; not a live observation/);
  assert.match(html, /Fixture data; not a live observation/);
  assert.match(html, /Authority flags: non_authoritative/);
  assert.match(html, /Latest timestamp in this returned page only/);
  assert.match(html, /<time dateTime="2027-01-15T08:01:40.000Z">[^<]+<\/time>/);
  assert.doesNotMatch(html, /<time dateTime="2027-01-15T08:01:40.000Z">2027-01-15T08:01:40/);
  assert.match(html, /Source labels are preserved; they do not prove live validation/);
});

test("ready panel announces source warnings and unknown page freshness", () => {
  const responseWithWarning = {
    timeline: {
      ...response.timeline,
      events: [
        { ...response.timeline.events[0], source: "event_bus", authority_flags: [] },
      ],
      last_occurred_at: null,
      warnings: ["partial_event_read"],
    },
  };
  const html = render(presentCanonicalEventResponse(responseWithWarning));
  assert.match(html, /role="status"[^>]*>Source warnings: partial_event_read/);
  assert.match(html, /Latest timestamp in this returned page only: not available/);
  assert.match(html, /Source labels are preserved; they do not prove live validation/);
});

test("error state is announced once with alert semantics", () => {
  const html = render({ phase: "error", message: "Request failed." });
  assert.match(html, /role="alert"/);
  assert.match(html, /Request failed\./);
  assert.doesNotMatch(html, /Canonical event read failed\. Canonical event read failed\./);
});

test("dashboard mounts an unavailable activity panel instead of requesting unscoped events", async () => {
  const featureRoot = fileURLToPath(new URL("../src/features/owner-performance/", import.meta.url));
  async function readFeatureSources(directory) {
    const entries = await readdir(directory, { withFileTypes: true });
    const nested = await Promise.all(entries.map(async (entry) => {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) return readFeatureSources(path);
      if (!/\.tsx?$/.test(entry.name)) return [];
      return [await readFile(path, "utf8")];
    }));
    return nested.flat();
  }
  const featureSource = (await readFeatureSources(featureRoot)).join("\n");
  assert.match(featureSource, /<OwnerActivityPanel\s+activity=\{OWNER_ACTIVITY_UNAVAILABLE\}\s*\/>/);
  assert.doesNotMatch(featureSource, /\b(?:fetchEvents|useEventRecords|fetchEventTimeline|useEventTimeline)\b/);
});
