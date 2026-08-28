# Design Document: Review Interface

## Overview

The Review Interface is a React + TypeScript single-page application view that provides compliance reviewers with a master-detail layout for inspecting and deciding on pipeline approval queue items. It consumes existing backend REST endpoints via polling, renders pipeline progress, and enforces atomic per-item decisions with optimistic UI updates.

**Key principles:**

- **Polling-driven freshness** — The UI fetches queue and progress data at a configurable interval (default 10s) without WebSocket infrastructure.
- **Optimistic UI** — Decision submissions update local state immediately, rolling back on failure.
- **Atomic isolation** — Each decision targets exactly one item; other items are never modified.
- **Keyboard-first accessibility** — Full keyboard navigation, ARIA labeling, and focus management.
- **Responsive layout** — Master-detail on desktop, stacked single-column on mobile (< 768px breakpoint).

The interface integrates into the existing React Router multi-page shell and uses Tailwind CSS with Radix UI headless components for accessible, unstyled primitives.

---

## Architecture

### Component Tree

```
App Shell (React Router)
└── /review (route)
    └── ReviewPage
        ├── TopBar
        │   ├── RunSelector
        │   └── StatusBadge
        ├── ProgressStepper
        └── MasterDetail
            ├── QueueList (left panel)
            │   ├── QueueFilters
            │   ├── QueueSortControls
            │   ├── QueueItemCard[] (virtualized)
            │   └── QueueSummaryBar (total/pending counts)
            └── DetailPanel (right panel)
                ├── PayloadView
                ├── CitationList
                │   └── CitationChip[]
                ├── SourceLocationTable
                └── DecisionControls
                    ├── ApproveButton
                    ├── RejectButton
                    └── JustificationInput
```

### Data Flow

```
┌─────────────────────────────────────────────────────────────┐
│                       PollingService                         │
│  (usePolling hook — configurable interval, visibility-aware)│
└──────────────┬──────────────────────────────────┬───────────┘
               │                                  │
               ▼                                  ▼
┌──────────────────────────┐   ┌──────────────────────────────┐
│   QueueStore (Zustand)   │   │  RunProgressStore (Zustand)  │
│  - items: QueueItem[]    │   │  - current_node: string      │
│  - total: number         │   │  - completed_nodes: string[] │
│  - pending: number       │   │  - node_status: string       │
│  - selectedItemId: str   │   │  - run_status: string        │
│  - optimisticUpdates: {} │   └──────────────────────────────┘
└──────────────────────────┘
               │
               ▼
┌──────────────────────────┐
│     DecisionService      │
│  POST /items/{id}/decide │
│  (optimistic + rollback) │
└──────────────────────────┘
```

---

## Components and Interfaces

### PollingService

A custom React hook (`usePolling`) that manages data freshness:

```typescript
interface PollingConfig {
  intervalMs: number;       // default: 10_000
  enabled: boolean;         // tied to document.visibilityState
  runId: string | null;
}

function usePolling(config: PollingConfig): {
  isPolling: boolean;
  lastFetchedAt: Date | null;
  error: Error | null;
  connectionLost: boolean;
}
```

**Behavior:**
- Fetches `GET /approval/runs/{run_id}/queue` and run progress at `intervalMs`
- Pauses when `document.visibilityState === "hidden"`
- Resumes with immediate fetch when visibility returns to `"visible"`
- On network error: sets `connectionLost = true`, preserves local state, retries next interval
- On success after error: clears `connectionLost`, merges new data

### QueueStore

Client-side state management using Zustand:

```typescript
interface QueueState {
  runId: string | null;
  items: QueueItem[];
  total: number;
  pending: number;
  selectedItemId: string | null;
  optimisticStatuses: Record<string, ItemStatus>;  // itemId → optimistic status
  filters: QueueFilters;
  sortBy: SortField;
  sortDirection: "asc" | "desc";

  // Actions
  setRunId: (runId: string) => void;
  mergeItems: (items: QueueItem[], total: number, pending: number) => void;
  selectItem: (itemId: string) => void;
  applyOptimisticUpdate: (itemId: string, status: ItemStatus) => void;
  rollbackOptimisticUpdate: (itemId: string) => void;
  clearOptimisticUpdate: (itemId: string) => void;
  setFilters: (filters: QueueFilters) => void;
  setSortBy: (field: SortField, direction: "asc" | "desc") => void;
  reset: () => void;
}

interface QueueFilters {
  itemType: ItemType | null;       // "finding" | "conflict" | "proposed_update" | null
  unverifiableOnly: boolean;
}

type SortField = "item_type" | "queued_at";
```

**Merge strategy:** When `mergeItems` is called from polling, items are replaced with fresh data but `selectedItemId` and scroll position are preserved. Optimistic statuses override server-reported statuses until cleared.

### DecisionService

Handles the decision submission lifecycle:

```typescript
interface DecisionRequest {
  itemId: string;
  decision: "approved" | "rejected";
  reviewerId: string;
  justification: string;
}

interface DecisionService {
  submit(req: DecisionRequest): Promise<DecisionResponse>;
}
```

**Optimistic flow:**
1. Call `applyOptimisticUpdate(itemId, decision)` → UI updates immediately
2. POST to `/approval/items/{item_id}/decide`
3. On success: `clearOptimisticUpdate(itemId)` (server data will match on next poll)
4. On failure: `rollbackOptimisticUpdate(itemId)` → status reverts to "pending", error toast shown
5. On 409: refresh item from server, show "already decided" notification

### ProgressStepper

Derives stage status from pipeline state:

```typescript
interface StageDefinition {
  name: string;
  nodes: string[];
}

const STAGES: StageDefinition[] = [
  { name: "Understand", nodes: ["ingest", "extract_text", "classify_document", "chunk", "embed"] },
  { name: "Examine",    nodes: ["extract_claims", "match_rules", "match_rules_against_sources", "merge_findings", "score_confidence"] },
  { name: "Stay-Alive", nodes: ["route_to_queue", "human_review", "finalize"] },
];

type StageStatus = "complete" | "in-progress" | "pending";

function deriveStageStatus(
  stage: StageDefinition,
  completedNodes: string[],
  currentNode: string | null
): StageStatus {
  const allComplete = stage.nodes.every(n => completedNodes.includes(n));
  if (allComplete) return "complete";
  const hasRunning = currentNode !== null && stage.nodes.includes(currentNode);
  if (hasRunning) return "in-progress";
  return "pending";
}
```

### RunSelector

```typescript
interface RunSelectorProps {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}

interface RunSummary {
  id: string;
  status: "running" | "completed" | "failed" | "paused";
  started_at: string;
}
```

**On run switch:** Calls `QueueStore.reset()` then `QueueStore.setRunId(newRunId)`, triggering an immediate fetch.

### CitationChip

```typescript
interface CitationChipProps {
  sourceLocation: SourceLocation | null;
}

// Rendering logic:
// - If sourceLocation is null or sourceLocation.source_span is null:
//     → render "[citation unverifiable]" in muted gray
// - If sourceLocation has a valid source_span:
//     → render clause_ref (or "p.{page_number}") in standard text color
```

### QueueItemCard

```typescript
interface QueueItemCardProps {
  item: QueueItem;
  isSelected: boolean;
  isLoading: boolean;    // true while optimistic update in-flight
  onClick: () => void;
}
```

Renders: item_type badge, payload summary (first 80 chars), status chip with color mapping.

### DecisionControls

```typescript
interface DecisionControlsProps {
  item: QueueItem;
  onDecide: (decision: "approved" | "rejected", justification: string) => void;
  isSubmitting: boolean;
}
```

- Shows Approve/Reject buttons only when `item.status === "pending"`
- Requires non-empty justification before enabling submit
- Disables buttons while `isSubmitting` is true

---

## Data Models

### Frontend TypeScript Types

```typescript
// Mirrors backend QueueItemResponse
interface QueueItem {
  id: string;
  run_id: string;
  item_type: "finding" | "conflict" | "proposed_update";
  payload: QueueItemPayload;
  status: "pending" | "approved" | "rejected";
  queued_at: string;           // ISO 8601
  decided_at: string | null;
  decision: "approved" | "rejected" | null;
  reviewer_id: string | null;
  justification: string | null;
}

interface QueueItemPayload {
  summary: string;
  details: Record<string, unknown>;
  source_citations: SourceCitation[];
}

interface SourceCitation {
  claim_id: string;
  claim_text: string;
  citation_status: "grounded" | "unverifiable";
  source_location: SourceLocation | null;
}

interface SourceLocation {
  page_number: number | null;
  section_id: string | null;
  start_offset: number;
  end_offset: number;
  clause_ref: string | null;
}

// API responses
interface QueueListResponse {
  run_id: string;
  items: QueueItem[];
  total: number;
  pending: number;
}

interface DecisionResponse {
  item_id: string;
  decision: "approved" | "rejected";
  success: boolean;
  error: string | null;
}

// Pipeline progress (from run history or progress endpoint)
interface PipelineProgress {
  current_node: string | null;
  completed_nodes: string[];
  node_status: "completed" | "skipped" | "error" | null;
  run_status: "running" | "completed" | "failed" | "paused";
}

// Run summary for selector
interface RunSummary {
  id: string;
  status: "running" | "completed" | "failed" | "paused";
  started_at: string;
  ended_at: string | null;
}
```

### Status Color Mapping

```typescript
const STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  approved: "bg-green-500/20 text-green-300 border-green-500/40",
  rejected: "bg-red-500/20 text-red-300 border-red-500/40",
  unverifiable: "bg-gray-500/20 text-gray-400 border-gray-500/40",
};
```

---

## API Integration

### Endpoint Mapping

| Frontend Action | HTTP Method | Endpoint | Response Type |
|----------------|-------------|----------|---------------|
| Load queue for run | GET | `/approval/runs/{run_id}/queue` | `QueueListResponse` |
| Load item detail | GET | `/approval/items/{item_id}` | `QueueItem` |
| Submit decision | POST | `/approval/items/{item_id}/decide` | `DecisionResponse` |
| Load available runs | POST | `/runs` | `CreateRunResponse` (list variant) |
| Resume a run | POST | `/runs/{run_id}/resume` | `ResumeRunResponse` |
| Load run history/progress | GET | `/runs/{run_id}/history` | `RunHistoryResponse` |

### Error Handling

| HTTP Status | Handling |
|-------------|----------|
| 200 | Process response, update store |
| 404 | Item not found — remove from local store, show toast |
| 409 | Item already decided — refresh from server, show notification |
| 5xx | Network/server error — preserve local state, show connection-lost indicator |
| Network failure | Same as 5xx — `connectionLost = true`, retry next interval |

---

## Keyboard Navigation

| Key | Context | Action |
|-----|---------|--------|
| `↑` / `↓` | Queue List focused | Move selection to previous/next item |
| `Enter` | Queue List item focused | Open item in Detail Panel |
| `a` | Detail Panel focused | Focus Approve button |
| `r` | Detail Panel focused | Focus Reject button |
| `Escape` | Detail Panel focused | Return focus to Queue List |
| `Tab` | Anywhere | Standard tab order through interactive elements |

Focus management: After a decision is submitted, focus moves to the next pending item in the queue list (skipping decided items).

---

## Responsive Layout

| Viewport | Layout | Behavior |
|----------|--------|----------|
| ≥ 768px | Side-by-side master-detail | Queue List (40%) + Detail Panel (60%) |
| < 768px | Stacked single-column | Queue List view with "Back" navigation; selecting an item shows Detail view |

The breakpoint is implemented via Tailwind's `md:` responsive prefix. On mobile, a navigation state (`"list" | "detail"`) controls which panel is visible.

---

## File Structure

```
frontend/src/
├── pages/
│   └── ReviewPage.tsx
├── components/
│   └── review/
│       ├── TopBar.tsx
│       ├── RunSelector.tsx
│       ├── StatusBadge.tsx
│       ├── ProgressStepper.tsx
│       ├── MasterDetail.tsx
│       ├── QueueList.tsx
│       ├── QueueItemCard.tsx
│       ├── QueueFilters.tsx
│       ├── QueueSortControls.tsx
│       ├── QueueSummaryBar.tsx
│       ├── DetailPanel.tsx
│       ├── PayloadView.tsx
│       ├── CitationChip.tsx
│       ├── CitationList.tsx
│       ├── SourceLocationTable.tsx
│       ├── DecisionControls.tsx
│       └── ConnectionLostBanner.tsx
├── hooks/
│   ├── usePolling.ts
│   ├── useKeyboardNavigation.ts
│   └── useFocusManagement.ts
├── stores/
│   ├── queueStore.ts
│   └── runProgressStore.ts
├── services/
│   ├── approvalApi.ts
│   └── decisionService.ts
├── utils/
│   ├── stageDerivation.ts
│   ├── filterSort.ts
│   └── citationHelpers.ts
└── types/
    └── review.ts
```

---

## Error Handling

### Decision Submission Errors

1. **Network failure during POST**: Rollback optimistic update, show error toast with retry option
2. **HTTP 409 (already decided)**: Fetch fresh item state, update local store, show info notification
3. **HTTP 404 (item not found)**: Remove item from local store, show warning toast
4. **HTTP 5xx**: Rollback optimistic update, show generic server error toast

### Polling Errors

1. **Network failure**: Set `connectionLost = true`, display banner, preserve all local state
2. **HTTP 5xx from queue endpoint**: Same as network failure treatment
3. **Recovery**: On next successful poll, clear `connectionLost`, merge fresh data

### Run Resume Errors

1. **POST /runs/{run_id}/resume fails**: Show error toast, keep current state unchanged
2. **Success**: Refresh progress stepper and status badge from response

---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Citation Chip Rendering Correctness

*For any* QueueItem payload containing source citations, if a citation has a null source_location or null source_span, the rendered chip SHALL display "[citation unverifiable]"; if it has a valid source_location with a source_span, the rendered chip SHALL display the clause_ref or page reference.

**Validates: Requirements 1.3, 1.4**

### Property 2: Queue Item Display Completeness

*For any* QueueListResponse with N items, the rendered Queue_List SHALL contain exactly N item cards, each displaying the correct item_type, a payload-derived summary, and a status chip whose color matches the item's status, and the summary bar SHALL display the response's total and pending counts.

**Validates: Requirements 1.1, 1.2, 1.5**

### Property 3: Filter Correctness

*For any* queue of items and any applied filter (by item_type or by unverifiable-citation presence), the filtered result SHALL contain exactly those items from the original set that match the filter predicate, and no others.

**Validates: Requirements 2.1, 2.2**

### Property 4: Sort Correctness

*For any* queue of items and any applied sort criterion (item_type or queued_at) with a direction (asc/desc), the resulting list SHALL be ordered according to that criterion and direction.

**Validates: Requirements 2.3**

### Property 5: Decision Button Visibility

*For any* QueueItem displayed in the Detail Panel, the Approve and Reject buttons SHALL be visible if and only if the item's effective status is "pending".

**Validates: Requirements 3.2, 3.6**

### Property 6: Justification Required for Decision

*For any* decision submission attempt, the submission SHALL be blocked (button disabled or form invalid) if the justification text is empty or whitespace-only.

**Validates: Requirements 3.3**

### Property 7: Optimistic Update Immediacy

*For any* decision submission on a pending item, the local item status SHALL transition to the submitted decision value synchronously before the network response is received.

**Validates: Requirements 4.1**

### Property 8: Rollback on Decision Failure

*For any* decision submission where the POST request fails (network error or non-2xx response other than 409), the local item status SHALL revert to "pending" and an error notification SHALL be displayed.

**Validates: Requirements 4.2**

### Property 9: Decision Isolation

*For any* queue containing N items and any single decision submitted on item X, all items Y where Y ≠ X SHALL have unchanged status, payload, and metadata after the decision is processed.

**Validates: Requirements 5.1, 5.2**

### Property 10: Progress Stepper Stage Derivation

*For any* pipeline state (current_node, completed_nodes), each of the three stages (Understand, Examine, Stay-Alive) SHALL be marked "complete" if all its constituent nodes appear in completed_nodes, "in-progress" if current_node is one of its constituent nodes, and "pending" otherwise.

**Validates: Requirements 6.3, 6.4, 6.5**

### Property 11: Run Switch Clears State

*For any* run switch from run A to run B, the queue store SHALL contain zero items from run A after the switch, and all subsequently displayed items SHALL belong exclusively to run B.

**Validates: Requirements 7.2, 7.4**

### Property 12: Polling Merge Preserves Selection

*For any* poll update that returns new queue data while the reviewer has a selected item, if that item still exists in the new data, the selection SHALL be preserved; the reviewer's scroll position SHALL not be disrupted.

**Validates: Requirements 8.3**

### Property 13: Network Error Preserves Local State

*For any* network error during a polling fetch, the local queue state (items, selection, optimistic updates) SHALL remain unchanged, and a connection-lost indicator SHALL be displayed.

**Validates: Requirements 11.3**

### Property 14: Focus Advances After Decision

*For any* successful decision submission, keyboard focus SHALL move to the next item in the Queue_List that has "pending" status, or remain on the current position if no pending items remain.

**Validates: Requirements 9.4**

### Property 15: Cross-Run Item Isolation

*For any* state of the Review Interface with a selected run, every QueueItem displayed in the Queue_List SHALL have a run_id matching the currently selected run. No item from a different run SHALL ever appear in the list.

**Validates: Requirements 7.4**


---

## Testing Strategy

### Unit Tests (Vitest + React Testing Library)

- **Component rendering**: Verify each component renders correctly given props (QueueItemCard, CitationChip, ProgressStepper, StatusBadge)
- **Decision controls**: Verify button visibility based on item status, justification validation
- **Filter/sort logic**: Verify pure filter and sort utility functions produce correct outputs

### Property-Based Tests (fast-check + Vitest)

Properties 1–15 above are implemented as property-based tests with minimum 100 iterations each. Key generators:

- **QueueItem generator**: Produces items with random item_type, status, payload with 0–5 source citations (mix of grounded/unverifiable)
- **QueueListResponse generator**: Produces responses with 0–50 items, valid total/pending counts
- **PipelineProgress generator**: Produces valid current_node/completed_nodes combinations respecting stage ordering
- **Filter/Sort generator**: Produces random filter and sort combinations

### Integration Tests (Playwright)

As specified in Requirement 12:
- Approve flow: select run → select pending item → submit approval → verify status update
- Reject flow: select run → submit rejection → verify isolation (other items unchanged)
- Kill/restart: simulate backend restart → trigger resume → verify persistence and stepper update

### Accessibility Testing

- axe-core integration in Vitest for automated ARIA/contrast checks
- Manual testing with screen reader (VoiceOver) for keyboard flow verification
- Focus management verified via unit tests (focus moves to next pending after decision)
