import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

const BASE = (import.meta.env.VITE_API_URL as string) ?? "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json() as T;
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json() as T;
}

// api/routes/services.py's scalar params (product, category, price, ...)
// are plain FastAPI function args, which bind from the query string, not a
// JSON body — dict-typed params (validation, kill_criteria, ...) are the
// only ones that bind from a JSON body. This helper sends both: scalars as
// a query string, an optional dict payload as the JSON body.
async function postServiceCall<T>(
  path: string,
  query: Record<string, string | number | boolean | undefined>,
  body?: Record<string, unknown>
): Promise<T> {
  const qs = new URLSearchParams();
  Object.entries(query).forEach(([k, v]) => {
    if (v !== undefined) qs.set(k, String(v));
  });
  const url = `${BASE}${path}${qs.toString() ? `?${qs}` : ""}`;
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body != null ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json() as T;
}

const FAST = 5_000;
const MED  = 15_000;
const SLOW = 60_000;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyData = any;

export const useMetricsData       = () => useQuery<AnyData>({ queryKey: ["metrics"],            queryFn: () => get("/metrics"),                         refetchInterval: FAST });
export const useSnapshot          = () => useQuery<AnyData>({ queryKey: ["snapshot"],           queryFn: () => get("/snapshot"),                        refetchInterval: FAST });
export const useOpportunities     = () => useQuery<AnyData>({ queryKey: ["opportunities"],      queryFn: () => get("/opportunities?limit=30"),           refetchInterval: MED  });
export const useCampaigns         = () => useQuery<AnyData>({ queryKey: ["campaigns"],          queryFn: () => get("/campaigns"),                       refetchInterval: MED  });
export const useCreatives         = () => useQuery<AnyData>({ queryKey: ["creatives"],          queryFn: () => get("/creatives"),                       refetchInterval: MED  });
export const useGeo               = () => useQuery<AnyData>({ queryKey: ["geo"],                queryFn: () => get("/geo"),                             refetchInterval: MED  });
export const useAlerts            = () => useQuery<AnyData>({ queryKey: ["alerts"],             queryFn: () => get("/alerts"),                          refetchInterval: FAST });
export const useRisk              = () => useQuery<AnyData>({ queryKey: ["risk"],               queryFn: () => get("/risk"),                            refetchInterval: MED  });
export const useRiskStatus        = () => useQuery<AnyData>({ queryKey: ["risk_status"],        queryFn: () => get("/risk/status"),                     refetchInterval: FAST });
export const useAgents            = () => useQuery<AnyData>({ queryKey: ["agents"],             queryFn: () => get("/agents"),                          refetchInterval: MED  });
export const useRuntimeTasks      = () => useQuery<AnyData>({ queryKey: ["runtime_tasks"],      queryFn: () => get("/runtime/tasks"),                   refetchInterval: FAST });
export const useEvents            = (limit = 200) => useQuery<AnyData>({ queryKey: ["events", limit], queryFn: () => get(`/events?limit=${limit}`),    refetchInterval: FAST });
export const usePredictionErrors  = () => useQuery<AnyData>({ queryKey: ["pred_errors"],        queryFn: () => get("/prediction_errors?limit=100"),     refetchInterval: MED  });
export const useCalibration       = () => useQuery<AnyData>({ queryKey: ["calibration"],        queryFn: () => get("/simulation/calibration"),          refetchInterval: SLOW });
export const useSimulationScores  = () => useQuery<AnyData>({ queryKey: ["sim_scores"],         queryFn: () => get("/simulation/scores?limit=20"),      refetchInterval: MED  });
export const usePlaybook          = () => useQuery<AnyData>({ queryKey: ["playbook"],           queryFn: () => get("/playbook"),                        refetchInterval: MED  });
export const usePortfolio         = () => useQuery<AnyData>({ queryKey: ["portfolio"],          queryFn: () => get("/portfolio"),                       refetchInterval: MED  });
export const useCapitalAllocation = () => useQuery<AnyData>({ queryKey: ["capital_allocation"], queryFn: () => get("/capital_allocation"),              refetchInterval: MED  });
export const useMacro             = () => useQuery<AnyData>({ queryKey: ["macro"],              queryFn: () => get("/macro"),                           refetchInterval: SLOW });
export const useCausal            = () => useQuery<AnyData>({ queryKey: ["causal"],             queryFn: () => get("/causal"),                          refetchInterval: SLOW });
export const useAccounts          = () => useQuery<AnyData>({ queryKey: ["accounts"],           queryFn: () => get("/accounts"),                        refetchInterval: MED  });
export const usePhase             = () => useQuery<AnyData>({ queryKey: ["phase"],              queryFn: () => get("/phase"),                           refetchInterval: MED  });
export const useBandit            = () => useQuery<AnyData>({ queryKey: ["bandit"],             queryFn: () => get("/bandit"),                          refetchInterval: SLOW });

export function useTriggerCycle() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => post("/cycle"), onSuccess: () => qc.invalidateQueries() });
}
export function usePauseRunner() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => post("/runner/pause"), onSuccess: () => qc.invalidateQueries({ queryKey: ["snapshot"] }) });
}
export function useResumeRunner() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => post("/runner/resume"), onSuccess: () => qc.invalidateQueries({ queryKey: ["snapshot"] }) });
}
export function useActivateKillSwitch() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: (reason: string) => post("/risk/killswitch/activate", { reason }), onSuccess: () => qc.invalidateQueries() });
}
export function useDeactivateKillSwitch() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => post("/risk/killswitch/deactivate"), onSuccess: () => qc.invalidateQueries() });
}
export function useCampaignOverride() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: ({ id, action }: { id: string; action: string }) => post(`/campaigns/${id}/override`, { action }), onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }) });
}
export function useTikTokLaunch() {
  const qc = useQueryClient();
  return useMutation({ mutationFn: () => post("/tiktok/launch"), onSuccess: () => qc.invalidateQueries() });
}

// ── services.* module routes (api/routes/services.py) ───────────────────
// Form-submitted actions, not polling reads — mutation hooks, matching the
// pattern above, not the useQuery polling hooks used for read-only panels.

export interface UnitEconomicsInput {
  product: string; cost: number; price: number; shipping?: number;
  category?: string; geo?: string; workspace?: string;
}
export function useUnitEconomics() {
  return useMutation({
    mutationFn: (input: UnitEconomicsInput) =>
      postServiceCall<AnyData>("/api/services/unit-economics", { ...input }),
  });
}

export interface EcommerceOperatorInput {
  product: string; roas: number; category?: string; budget_ceiling?: number;
  attribution_method?: string; proposed_scale_amount?: number;
  live_action?: boolean; workspace?: string;
  validation?: Record<string, unknown>; unit_economics?: Record<string, unknown>;
  supplier_assumptions?: Record<string, unknown>; kill_criteria?: Record<string, unknown>;
}
export function useEcommerceOperator() {
  return useMutation({
    mutationFn: ({
      validation, unit_economics, supplier_assumptions, kill_criteria, ...query
    }: EcommerceOperatorInput) =>
      postServiceCall<AnyData>("/api/services/ecommerce-operator", query, {
        validation, unit_economics, supplier_assumptions, kill_criteria,
      }),
  });
}

export interface ProductAuditInput {
  product: string; category?: string; price?: number; workspace?: string;
}
export function useProductAudit() {
  return useMutation({
    mutationFn: (input: ProductAuditInput) =>
      postServiceCall<AnyData>("/api/services/product-audit", { ...input }),
  });
}

export interface CreativeGrowthInput {
  product: string; category?: string; workspace?: string;
}
export function useCreativeGrowth() {
  return useMutation({
    mutationFn: (input: CreativeGrowthInput) =>
      postServiceCall<AnyData>("/api/services/creative-growth", { ...input }),
  });
}

export interface CustomerIntelligenceInput {
  business_type: string; vertical?: string; target_geo?: string;
  category?: string; workspace?: string;
}
export function useCustomerIntelligence() {
  return useMutation({
    mutationFn: (input: CustomerIntelligenceInput) =>
      postServiceCall<AnyData>("/api/services/customer-intelligence", { ...input }),
  });
}

export interface DigitalProductInput {
  offer_name: string; product_type?: string; target_customer?: string;
  transformation_promised?: string; price?: number; target_buyers?: number;
  has_existing_audience?: boolean; workspace?: string;
}
export function useDigitalProduct() {
  return useMutation({
    mutationFn: (input: DigitalProductInput) =>
      postServiceCall<AnyData>("/api/services/digital-product", { ...input }),
  });
}

export interface SalesAutomationInput {
  vertical: string; workspace?: string;
}
export function useSalesAutomation() {
  return useMutation({
    mutationFn: ({ vertical, workspace }: SalesAutomationInput) =>
      postServiceCall<AnyData>("/api/services/sales-automation", { vertical, workspace }),
  });
}
