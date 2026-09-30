import { AlertTriangle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { NoticeTone, OwnerNotice } from "../contracts/ownerDashboard";

const TONE_CLASS: Record<NoticeTone, string> = {
  info: "border-sky-500/30 bg-sky-500/10 text-sky-100",
  warning: "border-amber-500/30 bg-amber-500/10 text-amber-100",
  danger: "border-rose-500/40 bg-rose-500/10 text-rose-100",
};

export function NoticeList({ notices }: { notices: OwnerNotice[] }) {
  if (notices.length === 0) return null;
  return (
    <section aria-label="Data provenance and integrity notices" className="space-y-2">
      {notices.map((notice) => (
        <div
          key={`${notice.id}-${notice.title}`}
          role={notice.tone === "danger" ? "alert" : "status"}
          data-notice={notice.id}
          className={cn("flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-sm", TONE_CLASS[notice.tone])}
        >
          {notice.tone === "info" ? (
            <Info aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          ) : (
            <AlertTriangle aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
          )}
          <p className="min-w-0 break-words">
            <strong className="font-semibold">{notice.title}.</strong> {notice.detail}
          </p>
        </div>
      ))}
    </section>
  );
}
