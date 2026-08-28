import { useEffect, useRef, useCallback, useState } from "react";
import { useQueueStore } from "@/stores/queueStore";
import { useRunProgressStore } from "@/stores/runProgressStore";
import { usePolling } from "@/hooks/usePolling";
import { useKeyboardNavigation } from "@/hooks/useKeyboardNavigation";
import { useFocusManagement } from "@/hooks/useFocusManagement";
import { submitItemDecision } from "@/services/decisionService";
import { fetchRuns } from "@/services/approvalApi";
import { applyFilters, applySorting } from "@/utils/filterSort";
import { DEFAULT_POLLING_INTERVAL_MS } from "@/utils/constants";
import { TopBar } from "@/components/review/TopBar";
import { ProgressStepper } from "@/components/review/ProgressStepper";
import { ConnectionLostBanner } from "@/components/review/ConnectionLostBanner";
import { MasterDetail } from "@/components/review/MasterDetail";
import { QueueList } from "@/components/review/QueueList";
import { DetailPanel } from "@/components/review/DetailPanel";

/**
 * ReviewPage — the main orchestrating component for the review interface.
 * Composes TopBar, ProgressStepper, ConnectionLostBanner, and MasterDetail
 * (QueueList + DetailPanel). Connects stores, hooks, and services.
 *
 * Validates: Requirements 10.5, 7.2, 8.1
 */
export function ReviewPage() {
  // ─── Stores ────────────────────────────────────────────────────────────────
  const {
    items,
    total,
    pending,
    selectedItemId,
    optimisticStatuses,
    filters,
    sortBy,
    sortDirection,
    setRunId,
    selectItem,
    reset: resetQueue,
  } = useQueueStore();

  const {
    completedNodes,
    currentNode,
    runStatus,
    runs,
    selectedRunId,
    setRuns,
    setSelectedRunId,
  } = useRunProgressStore();

  // ─── Local State ───────────────────────────────────────────────────────────
  const [isSubmitting, setIsSubmitting] = useState(false);

  // ─── Refs ──────────────────────────────────────────────────────────────────
  const listRef = useRef<HTMLElement>(null);
  const approveButtonRef = useRef<HTMLButtonElement>(null);
  const rejectButtonRef = useRef<HTMLButtonElement>(null);

  // ─── Derived Data ──────────────────────────────────────────────────────────
  const filteredItems = applyFilters(items, filters);
  const sortedItems = applySorting(filteredItems, sortBy, sortDirection);
  const selectedItem = sortedItems.find((item) => item.id === selectedItemId) ?? null;

  // ─── Polling ───────────────────────────────────────────────────────────────
  const { connectionLost } = usePolling({
    intervalMs: DEFAULT_POLLING_INTERVAL_MS,
    enabled: true,
    runId: selectedRunId,
  });

  // ─── Keyboard Navigation ──────────────────────────────────────────────────
  useKeyboardNavigation({
    items: sortedItems,
    selectedItemId,
    onSelectItem: selectItem,
    listRef,
    approveButtonRef,
    rejectButtonRef,
  });

  // ─── Focus Management ─────────────────────────────────────────────────────
  const { advanceFocusAfterDecision } = useFocusManagement({
    items: sortedItems,
    selectedItemId,
    onSelectItem: selectItem,
    listRef,
  });

  // ─── Effects ───────────────────────────────────────────────────────────────

  // Fetch available runs on mount
  useEffect(() => {
    async function loadRuns() {
      try {
        const availableRuns = await fetchRuns();
        setRuns(availableRuns);
        // Auto-select the first run if none selected
        if (availableRuns.length > 0 && !selectedRunId) {
          const firstRunId = availableRuns[0].id;
          setSelectedRunId(firstRunId);
          setRunId(firstRunId);
        }
      } catch {
        // Runs will be empty; polling will retry
      }
    }
    loadRuns();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ─── Handlers ──────────────────────────────────────────────────────────────

  const handleSelectRun = useCallback(
    (runId: string) => {
      resetQueue();
      setSelectedRunId(runId);
      setRunId(runId);
    },
    [resetQueue, setSelectedRunId, setRunId]
  );

  const handleDecision = useCallback(
    async (decision: "approved" | "rejected", justification: string) => {
      if (!selectedItemId) return;

      setIsSubmitting(true);
      try {
        await submitItemDecision({
          itemId: selectedItemId,
          decision,
          reviewerId: "current-user", // placeholder until auth integration
          justification,
        });
        advanceFocusAfterDecision();
      } finally {
        setIsSubmitting(false);
      }
    },
    [selectedItemId, advanceFocusAfterDecision]
  );

  const handleBack = useCallback(() => {
    // On mobile, deselect item to show the list view
    useQueueStore.setState({ selectedItemId: null });
  }, []);

  // ─── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="relative flex h-screen flex-col bg-surface-base text-white/90 overflow-hidden">
      {/* Background radial gradient for depth */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(99,102,241,0.05),transparent_50%)] pointer-events-none" aria-hidden="true" />

      <div className="relative flex flex-col h-full">
        <TopBar
          runs={runs}
          selectedRunId={selectedRunId}
          runStatus={runStatus}
          onSelectRun={handleSelectRun}
        />

        {selectedRunId !== "all" && (
          <ProgressStepper
            completedNodes={completedNodes}
            currentNode={currentNode}
          />
        )}

        <ConnectionLostBanner connectionLost={connectionLost} />

        <main className="flex-1 overflow-hidden">
          <MasterDetail
            hasSelection={selectedItemId !== null}
            onBack={handleBack}
            listPanel={
              <QueueList
                items={sortedItems}
                selectedItemId={selectedItemId}
                optimisticStatuses={optimisticStatuses}
                onSelectItem={selectItem}
                total={total}
                pending={pending}
              />
            }
            detailPanel={
              <DetailPanel
                item={selectedItem}
                onDecide={handleDecision}
                isSubmitting={isSubmitting}
              />
            }
          />
        </main>
      </div>
    </div>
  );
}

export default ReviewPage;
