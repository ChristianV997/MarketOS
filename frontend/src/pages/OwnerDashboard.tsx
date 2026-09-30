import { useState } from "react";
import { OwnerDashboardView } from "@/features/owner-dashboard/components/OwnerDashboardView";
import { useOwnerDashboard } from "@/features/owner-dashboard/hooks/useOwnerDashboard";

export default function OwnerDashboardPage() {
  const { viewModel, retry, isRetrying } = useOwnerDashboard();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [focusToken, setFocusToken] = useState(0);

  return (
    <OwnerDashboardView
      viewModel={viewModel}
      selectedId={selectedId}
      onSelect={(candidateId) => {
        setSelectedId(candidateId);
        setFocusToken((token) => token + 1);
      }}
      onRetry={retry}
      isRetrying={isRetrying}
      focusToken={focusToken}
    />
  );
}
