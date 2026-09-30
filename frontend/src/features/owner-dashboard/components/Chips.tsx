import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import type { EconomicsBasis, Readiness } from "../contracts/ownerDashboard";
import { BASIS_LABELS, recommendationLabel } from "../lib/labels";

export type ChipTone = "neutral" | "positive" | "info" | "caution" | "danger" | "muted";

const TONES: Record<ChipTone, string> = {
  neutral: "border-zinc-500/30 bg-zinc-800 text-zinc-300",
  positive: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  info: "border-sky-500/30 bg-sky-500/10 text-sky-300",
  caution: "border-amber-500/30 bg-amber-500/10 text-amber-300",
  danger: "border-rose-500/30 bg-rose-500/10 text-rose-300",
  muted: "border-zinc-700 bg-transparent text-zinc-400",
};

export function Chip({ tone = "neutral", children, title }: { tone?: ChipTone; children: ReactNode; title?: string }) {
  return (
    <span
      title={title}
      className={cn("inline-flex max-w-full items-center break-words rounded border px-1.5 py-0.5 text-[11px] font-medium", TONES[tone])}
    >
      {children}
    </span>
  );
}

const READINESS: Record<Readiness, { tone: ChipTone; label: string }> = {
  ready: { tone: "positive", label: "Research-ready" },
  not_ready: { tone: "caution", label: "Not ready" },
  blocked: { tone: "danger", label: "Blocked" },
  unknown: { tone: "muted", label: "Readiness unknown" },
};

export function ReadinessChip({ readiness }: { readiness: Readiness }) {
  const { tone, label } = READINESS[readiness];
  return (
    <Chip tone={tone} title="Research readiness is not launch authorization">
      {label}
    </Chip>
  );
}

const RECOMMENDATION_TONE: Record<string, ChipTone> = {
  attractive: "positive",
  acceptable: "info",
  needs_evidence: "caution",
  blocked: "danger",
};

export function RecommendationChip({ value }: { value: string | null }) {
  return <Chip tone={value ? (RECOMMENDATION_TONE[value] ?? "neutral") : "muted"}>{recommendationLabel(value)}</Chip>;
}

const EVIDENCE_CLASS: Record<string, { tone: ChipTone; label: string }> = {
  observed: { tone: "positive", label: "Observed" },
  derived: { tone: "info", label: "Derived" },
  fixture: { tone: "caution", label: "Fixture" },
  manual: { tone: "caution", label: "Manual" },
  simulated: { tone: "caution", label: "Simulated" },
  unknown: { tone: "muted", label: "Unknown" },
  unavailable: { tone: "muted", label: "Unavailable" },
  live_validated: { tone: "info", label: "Live validated (provider claim)" },
};

export function EvidenceClassChip({ value }: { value: string | null }) {
  if (value === null) return <Chip tone="muted">Unknown</Chip>;
  const known = EVIDENCE_CLASS[value];
  return <Chip tone={known?.tone ?? "neutral"}>{known?.label ?? value}</Chip>;
}

const BASIS_TONE: Record<EconomicsBasis, ChipTone> = {
  observed: "positive",
  manual: "info",
  derived: "neutral",
  assumed: "caution",
  fixture: "caution",
  unknown: "muted",
};

export function BasisChip({ basis }: { basis: EconomicsBasis }) {
  return <Chip tone={BASIS_TONE[basis]}>{BASIS_LABELS[basis]}</Chip>;
}
