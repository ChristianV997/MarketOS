/** Read-only browser client for the canonical-event operator routes. */

export type EventSource = "jsonl" | "supabase_staging";

export interface EventQueryParams {
  workspace_id?: string;
  event_type?: string;
  aggregate_type?: string;
  aggregate_id?: string;
  correlation_id?: string;
  source?: EventSource;
  limit?: number;
  offset?: number;
}

export interface EventRecordView {
  event_id: string;
  workspace_id: string | null;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  occurred_at: number;
  source: string;
  correlation_id: string | null;
  causation_id: string | null;
  replay_hash: string;
  payload_summary: Record<string, unknown>;
  metadata_summary: Record<string, unknown>;
  dry_run: boolean;
  advisory: boolean;
  read_only: boolean;
  pii_redacted: boolean;
  authority_flags: string[];
}

export interface EventTimeline {
  workspace_id: string | null;
  events: EventRecordView[];
  event_type_counts: Record<string, number>;
  aggregate_type_counts: Record<string, number>;
  first_occurred_at: number | null;
  last_occurred_at: number | null;
  warnings: string[];
}

export interface CommerceRunSummary {
  workspace_id: string | null;
  run_id: string;
  query: string;
  status: string;
  candidate_count: number;
  selected_candidate: string | null;
  economics_present: boolean;
  creative_packet_present: boolean;
  landing_page_packet_present: boolean;
  store_draft_packet_present: boolean;
  approval_packet_present: boolean;
  vendor_recommendations_present: boolean;
  event_count: number;
  warnings: string[];
  blockers: string[];
}

export interface ShopifyImportSummary {
  workspace_id: string | null;
  batch_id: string;
  product_count: number;
  variant_count: number;
  collection_count: number;
  order_count: number;
  line_item_count: number;
  customer_count: number;
  pii_redacted: boolean;
  observed_revenue_total: number;
  average_order_value: number;
  event_count: number;
  warnings: string[];
}

export interface EventsReadiness {
  jsonl_path_configured: boolean;
  supabase_staging: { configured: boolean; missing_env?: string[]; read_only: boolean; server_side_only: boolean; write_gate_enabled?: boolean };
  read_only: boolean;
  mutated: boolean;
}

export interface PublicCommerceRunRequest {
  query: string;
  workspace_id: string;
  max_signals: number;
  max_candidates: number;
  allow_public_network: boolean;
  include_shopify_fixture_context: boolean;
  source: "google_news_rss";
  event_target: "none" | "jsonl" | "supabase_staging" | "both";
  operator_note?: string;
}

export interface PublicCommerceRunReport {
  status: string;
  public_source_status: string;
  signal_count: number;
  candidate_count: number;
  selected_candidate: string | null;
  event_count: number;
  event_type_counts: Record<string, number>;
  write_targets: string[];
  warnings: string[];
  blockers: string[];
  read_only: boolean;
  advisory: boolean;
  mutated: boolean;
}

const baseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? (import.meta.env.VITE_API_URL as string | undefined) ?? "";

function queryString(params: EventQueryParams = {}): string {
  const query = new URLSearchParams();
  const allowed: Array<keyof EventQueryParams> = ["workspace_id", "event_type", "aggregate_type", "aggregate_id", "correlation_id", "source", "limit", "offset"];
  for (const key of allowed) {
    const value = params[key];
    if (value !== undefined && value !== "") query.set(key, String(value));
  }
  return query.toString() ? `?${query}` : "";
}

async function get<T>(path: string, params?: EventQueryParams): Promise<T> {
  const response = await fetch(`${baseUrl}${path}${queryString(params)}`, { method: "GET" });
  if (!response.ok) throw new Error(`Unable to load operator events (${response.status}).`);
  return response.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`Unable to run public Commerce MVP test (${response.status}).`);
  return response.json() as Promise<T>;
}

export const fetchEventTimeline = (params: EventQueryParams) => get<EventTimeline>("/api/events/timeline", params);
export const fetchEvents = (params: EventQueryParams) => get<{ timeline: EventTimeline }>("/api/events", params);
export const fetchCommerceRuns = (params: EventQueryParams) => get<{ runs: CommerceRunSummary[]; read_only: boolean }>("/api/events/commerce-runs", params);
export const fetchShopifyImports = (params: EventQueryParams) => get<{ imports: ShopifyImportSummary[]; read_only: boolean }>("/api/events/shopify-imports", params);
export const fetchEventsReadiness = () => get<EventsReadiness>("/api/events/readiness");
export const runPublicCommerceMvp = (request: PublicCommerceRunRequest) => post<PublicCommerceRunReport>("/api/commerce-mvp/public-run", request);
