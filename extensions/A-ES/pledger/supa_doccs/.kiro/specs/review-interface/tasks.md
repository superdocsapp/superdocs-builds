# Implementation Plan: Review Interface

## Overview

Build the compliance review interface as a React + TypeScript SPA view integrated into the existing app shell. The implementation proceeds from foundational types and stores through UI components, hooks, and services, culminating in accessibility wiring and integration tests. Each step builds incrementally on prior work, ensuring no orphaned code.

## Tasks

- [x] 1. Set up project structure, types, and tooling
  - [x] 1.1 Initialize frontend project with Vite, React, TypeScript, Tailwind CSS, and install dependencies
    - Initialize Vite project in `frontend/` with React + TypeScript template
    - Install dependencies: `zustand`, `@radix-ui/react-select`, `@radix-ui/react-dialog`, `@radix-ui/react-tooltip`, `tailwindcss`, `postcss`, `autoprefixer`, `react-router-dom`
    - Install dev dependencies: `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `fast-check`, `jsdom`, `@playwright/test`, `axe-core`, `vitest-axe`
    - Configure `tailwind.config.ts` with the deep navy/charcoal color palette and custom status colors
    - Configure `vitest.config.ts` with jsdom environment and setup file
    - _Requirements: 10.1_

  - [x] 1.2 Create shared TypeScript types and constants
    - Create `frontend/src/types/review.ts` with all interfaces: `QueueItem`, `QueueItemPayload`, `SourceCitation`, `SourceLocation`, `QueueListResponse`, `DecisionResponse`, `PipelineProgress`, `RunSummary`, `QueueFilters`, `SortField`
    - Create `frontend/src/utils/constants.ts` with `STATUS_COLORS` mapping, `STAGES` array for progress stepper, and polling default interval
    - _Requirements: 1.2, 6.1, 10.4_

- [x] 2. Implement state management stores
  - [x] 2.1 Implement the queue store with Zustand
    - Create `frontend/src/stores/queueStore.ts` implementing `QueueState` interface from design
    - Implement actions: `setRunId`, `mergeItems`, `selectItem`, `applyOptimisticUpdate`, `rollbackOptimisticUpdate`, `clearOptimisticUpdate`, `setFilters`, `setSortBy`, `reset`
    - Merge strategy: replace items but preserve `selectedItemId` and optimistic overrides
    - _Requirements: 1.1, 4.1, 4.2, 5.2, 7.2, 8.3_

  - [x] 2.2 Write property tests for queue store
    - **Property 9: Decision Isolation** — submitting a decision on item X leaves all other items unchanged
    - **Property 11: Run Switch Clears State** — switching runs clears all items from prior run
    - **Property 12: Polling Merge Preserves Selection** — merging new poll data preserves selectedItemId
    - **Validates: Requirements 5.1, 5.2, 7.2, 7.4, 8.3**

  - [x] 2.3 Implement the run progress store with Zustand
    - Create `frontend/src/stores/runProgressStore.ts` with state: `currentNode`, `completedNodes`, `nodeStatus`, `runStatus`, `runs`
    - Implement actions: `setProgress`, `setRuns`, `setSelectedRunId`, `reset`
    - _Requirements: 6.2, 7.1, 7.3_

- [x] 3. Implement API service and decision service layers
  - [x] 3.1 Create the approval API service
    - Create `frontend/src/services/approvalApi.ts` with typed fetch wrappers for all endpoints: `fetchQueue(runId)`, `fetchItem(itemId)`, `submitDecision(itemId, request)`, `fetchRuns()`, `resumeRun(runId)`, `fetchRunProgress(runId)`
    - Implement error classification: 404, 409, 5xx, and network failure handling
    - _Requirements: 1.1, 3.1, 3.4, 7.1, 11.2_

  - [x] 3.2 Create the decision service with optimistic update lifecycle
    - Create `frontend/src/services/decisionService.ts` implementing the 5-step optimistic flow from design
    - Step 1: `applyOptimisticUpdate` → Step 2: POST → Step 3: success `clearOptimisticUpdate` → Step 4: failure `rollbackOptimisticUpdate` + toast → Step 5: 409 refresh item
    - _Requirements: 3.4, 3.5, 4.1, 4.2, 5.1, 5.3_

  - [x] 3.3 Write property tests for decision service
    - **Property 7: Optimistic Update Immediacy** — local status transitions before network response
    - **Property 8: Rollback on Decision Failure** — status reverts to pending on POST failure
    - **Validates: Requirements 4.1, 4.2**

- [x] 4. Implement utility functions
  - [x] 4.1 Create stage derivation utility
    - Create `frontend/src/utils/stageDerivation.ts` with `deriveStageStatus(stage, completedNodes, currentNode)` function per design specification
    - Return "complete" | "in-progress" | "pending" for each stage
    - _Requirements: 6.3, 6.4, 6.5_

  - [x] 4.2 Write property test for stage derivation
    - **Property 10: Progress Stepper Stage Derivation** — stages correctly marked complete/in-progress/pending based on node state
    - **Validates: Requirements 6.3, 6.4, 6.5**

  - [x] 4.3 Create filter and sort utility functions
    - Create `frontend/src/utils/filterSort.ts` with `applyFilters(items, filters)` and `applySorting(items, sortBy, direction)` functions
    - Filter by `item_type` and by `unverifiableOnly` (items with at least one citation where `citation_status === "unverifiable"`)
    - Sort by `item_type` alphabetically or `queued_at` chronologically
    - _Requirements: 2.1, 2.2, 2.3, 2.4_

  - [x] 4.4 Write property tests for filter and sort utilities
    - **Property 3: Filter Correctness** — filtered result contains exactly matching items and no others
    - **Property 4: Sort Correctness** — result is ordered according to criterion and direction
    - **Validates: Requirements 2.1, 2.2, 2.3**

  - [x] 4.5 Create citation helper utilities
    - Create `frontend/src/utils/citationHelpers.ts` with `getCitationLabel(citation)` and `isUnverifiable(citation)` functions
    - Return "[citation unverifiable]" for null source_location or null source_span; clause_ref or "p.{page_number}" otherwise
    - _Requirements: 1.3, 1.4_

  - [x] 4.6 Write property test for citation helpers
    - **Property 1: Citation Chip Rendering Correctness** — label matches source_location/source_span presence
    - **Validates: Requirements 1.3, 1.4**

- [x] 5. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 6. Implement core UI components (atoms)
  - [x] 6.1 Implement StatusBadge component
    - Create `frontend/src/components/review/StatusBadge.tsx` rendering run status chip with color from `STATUS_COLORS`
    - Accept `status: "running" | "completed" | "failed" | "paused"` prop
    - Apply ARIA label describing the status
    - _Requirements: 7.3, 9.3, 10.4_

  - [x] 6.2 Implement CitationChip component
    - Create `frontend/src/components/review/CitationChip.tsx` using `getCitationLabel` utility
    - Render muted gray styling for unverifiable, standard text for grounded
    - _Requirements: 1.3, 1.4, 10.4_

  - [x] 6.3 Implement QueueItemCard component
    - Create `frontend/src/components/review/QueueItemCard.tsx` rendering item_type badge, payload summary (first 80 chars), status chip, and loading indicator for in-flight optimistic updates
    - Accept `item`, `isSelected`, `isLoading`, `onClick` props
    - Apply ARIA attributes: `role="option"`, `aria-selected`, `aria-busy`
    - _Requirements: 1.2, 4.3, 9.3_

  - [x] 6.4 Implement ProgressStepper component
    - Create `frontend/src/components/review/ProgressStepper.tsx` displaying three stages using `deriveStageStatus`
    - Render checkmark for complete, animated spinner for in-progress, muted circle for pending
    - Apply ARIA `role="progressbar"` or `role="list"` with stage status labels
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 9.3_

  - [x] 6.5 Implement ConnectionLostBanner component
    - Create `frontend/src/components/review/ConnectionLostBanner.tsx` displaying a dismissible warning banner when `connectionLost` is true
    - Apply ARIA `role="alert"` for screen reader announcement
    - _Requirements: 11.3, 9.3_

- [x] 7. Implement composite UI components
  - [x] 7.1 Implement RunSelector component
    - Create `frontend/src/components/review/RunSelector.tsx` using Radix UI Select primitive
    - Display available runs with status indicators, trigger `onSelectRun` callback
    - Apply ARIA label "Select pipeline run"
    - _Requirements: 7.1, 7.2, 9.3_

  - [x] 7.2 Implement QueueFilters and QueueSortControls components
    - Create `frontend/src/components/review/QueueFilters.tsx` with item_type filter (dropdown) and unverifiable-only toggle
    - Create `frontend/src/components/review/QueueSortControls.tsx` with sort field and direction controls
    - Both update queueStore on change; apply ARIA labels to all controls
    - _Requirements: 2.1, 2.2, 2.3, 9.3_

  - [x] 7.3 Implement DecisionControls component
    - Create `frontend/src/components/review/DecisionControls.tsx` with Approve/Reject buttons and JustificationInput textarea
    - Show buttons only when `item.status === "pending"`; disable submit when justification is empty
    - Wire `onDecide` callback; show loading state while submitting
    - _Requirements: 3.2, 3.3, 3.6, 9.2_

  - [x] 7.4 Write property tests for DecisionControls
    - **Property 5: Decision Button Visibility** — buttons visible iff status is pending
    - **Property 6: Justification Required** — submission blocked when justification empty
    - **Validates: Requirements 3.2, 3.3, 3.6**

  - [x] 7.5 Implement DetailPanel component
    - Create `frontend/src/components/review/DetailPanel.tsx` composing PayloadView, CitationList, SourceLocationTable, and DecisionControls
    - Create `frontend/src/components/review/PayloadView.tsx` rendering full item payload details
    - Create `frontend/src/components/review/CitationList.tsx` rendering array of CitationChip components
    - Create `frontend/src/components/review/SourceLocationTable.tsx` rendering source location metadata in a table
    - _Requirements: 3.1, 1.3, 1.4_

  - [x] 7.6 Implement QueueList component with QueueSummaryBar
    - Create `frontend/src/components/review/QueueList.tsx` rendering filtered/sorted QueueItemCards with virtualization
    - Create `frontend/src/components/review/QueueSummaryBar.tsx` displaying total and pending counts
    - Apply `role="listbox"` with `aria-label="Approval queue items"`
    - _Requirements: 1.1, 1.5, 2.4, 9.3_

  - [x] 7.7 Write property test for QueueList rendering
    - **Property 2: Queue Item Display Completeness** — rendered list contains exactly N cards matching response data
    - **Property 15: Cross-Run Item Isolation** — all displayed items have run_id matching selected run
    - **Validates: Requirements 1.1, 1.2, 1.5, 7.4**

- [x] 8. Implement hooks
  - [x] 8.1 Implement usePolling hook
    - Create `frontend/src/hooks/usePolling.ts` implementing visibility-aware polling per design spec
    - Fetch queue and progress at configurable interval; pause on `document.hidden`; resume with immediate fetch on visibility return
    - On network error: set `connectionLost`, preserve local state, retry next interval
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 11.3_

  - [x] 8.2 Write property test for polling behavior
    - **Property 13: Network Error Preserves Local State** — local queue state unchanged on network error, connectionLost indicator displayed
    - **Validates: Requirements 11.3**

  - [x] 8.3 Implement useKeyboardNavigation hook
    - Create `frontend/src/hooks/useKeyboardNavigation.ts` handling arrow keys for queue traversal, Enter for selection, `a`/`r` shortcuts for Approve/Reject focus, Escape to return to list
    - _Requirements: 9.1, 9.2_

  - [x] 8.4 Implement useFocusManagement hook
    - Create `frontend/src/hooks/useFocusManagement.ts` managing focus advancement after decision submission (move to next pending item)
    - Implement visible focus ring styling via Tailwind `ring-2 ring-offset-2` meeting WCAG 2.1 AA
    - _Requirements: 9.4, 9.5_

  - [x] 8.5 Write property test for focus advancement
    - **Property 14: Focus Advances After Decision** — focus moves to next pending item after successful decision
    - **Validates: Requirements 9.4**

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Assemble page layout and routing
  - [x] 10.1 Implement MasterDetail layout component
    - Create `frontend/src/components/review/MasterDetail.tsx` with responsive split: 40%/60% on desktop (`md:` breakpoint), stacked with navigation state on mobile
    - Implement mobile navigation state (`"list" | "detail"`) with back button
    - _Requirements: 10.2, 10.3_

  - [x] 10.2 Implement TopBar component
    - Create `frontend/src/components/review/TopBar.tsx` composing RunSelector and StatusBadge in a horizontal bar
    - _Requirements: 7.1, 7.3_

  - [x] 10.3 Implement ReviewPage and wire into React Router
    - Create `frontend/src/pages/ReviewPage.tsx` composing TopBar, ProgressStepper, MasterDetail (QueueList + DetailPanel)
    - Connect all stores, hooks (usePolling, useKeyboardNavigation, useFocusManagement), and services
    - Register `/review` route in the app shell's router configuration
    - _Requirements: 10.5, 7.2, 8.1_

  - [x] 10.4 Write unit tests for ReviewPage integration
    - Test that ReviewPage renders all sub-components correctly
    - Test that run switching triggers queue reset and refetch
    - Test responsive layout breakpoint behavior
    - _Requirements: 10.2, 10.3, 7.2_

- [x] 11. Implement resume and error recovery flows
  - [x] 11.1 Implement run resume functionality
    - Add resume button/action in TopBar that calls `POST /runs/{run_id}/resume`
    - On success: update ProgressStepper and StatusBadge from response
    - On failure: show error toast, preserve current state
    - _Requirements: 11.2_

  - [x] 11.2 Implement 409 conflict handling
    - In decision service: detect 409 response, fetch fresh item state from `GET /approval/items/{item_id}`, update store, show "already decided" notification
    - _Requirements: 5.3_

- [x] 12. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Integration tests with Playwright
  - [x] 13.1 Set up Playwright test infrastructure
    - Create `frontend/e2e/` directory with Playwright config
    - Create mock server utility for simulating backend API responses (queue, items, decisions, runs, progress)
    - Configure test fixtures with sample queue data (mix of pending/approved/rejected items with grounded and unverifiable citations)
    - _Requirements: 12.1, 12.2, 12.3_

  - [x] 13.2 Write Playwright test for approve flow
    - Navigate to `/review`, select a run, select a pending item, enter justification, click Approve, verify item status updates to approved in both detail panel and queue list
    - **Validates: Requirements 12.1**

  - [x] 13.3 Write Playwright test for reject flow with isolation verification
    - Navigate to `/review`, select a run, submit a reject decision, verify item status updates to rejected, verify all other queue items remain unchanged
    - **Validates: Requirements 12.2**

  - [x] 13.4 Write Playwright test for kill/restart resume path
    - Simulate backend restart (stop mock server, restart), trigger resume action, verify previously submitted decisions remain intact, verify progress stepper reflects resumed state
    - **Validates: Requirements 12.3**

- [x] 14. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The frontend project is initialized from scratch in `frontend/` since only a README placeholder exists
- All components use Radix UI headless primitives for accessibility and Tailwind CSS for styling
- The existing backend API endpoints (`/approval/*`, `/runs/*`) are consumed as-is

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["2.1", "2.3", "4.1", "4.3", "4.5"] },
    { "id": 3, "tasks": ["2.2", "4.2", "4.4", "4.6", "3.1"] },
    { "id": 4, "tasks": ["3.2", "3.3"] },
    { "id": 5, "tasks": ["6.1", "6.2", "6.3", "6.4", "6.5"] },
    { "id": 6, "tasks": ["7.1", "7.2", "7.3", "7.5", "7.6"] },
    { "id": 7, "tasks": ["7.4", "7.7", "8.1", "8.3", "8.4"] },
    { "id": 8, "tasks": ["8.2", "8.5"] },
    { "id": 9, "tasks": ["10.1", "10.2"] },
    { "id": 10, "tasks": ["10.3", "11.1", "11.2"] },
    { "id": 11, "tasks": ["10.4", "13.1"] },
    { "id": 12, "tasks": ["13.2", "13.3", "13.4"] }
  ]
}
```
