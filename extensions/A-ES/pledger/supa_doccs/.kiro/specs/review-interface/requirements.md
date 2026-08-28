# Requirements Document

## Introduction

The Review Interface is the primary human-facing surface for the SuperDocs agentic document-intelligence system. It presents Movement 1–3 pipeline outputs (findings, conflicts, and proposed updates) to compliance reviewers for item-by-item approval or rejection. The interface consumes existing backend REST endpoints via polling, renders a professional financial-compliance UI with a master-detail layout, and enforces the human-gate contract: each decision is atomic, independent, and durable.

## Glossary

- **Review_Interface**: The React + TypeScript single-page application view that displays approval queue items and accepts reviewer decisions.
- **Queue_List**: The left panel of the master-detail layout showing all approval queue items for the selected run.
- **Detail_Panel**: The right panel of the master-detail layout showing full item payload, source citations, and decision controls for a single selected item.
- **Progress_Stepper**: A visual component displaying pipeline movement completion (Understand → Examine → Stay-Alive) driven by checkpointer state.
- **Run_Selector**: A control in the top app bar allowing the reviewer to switch between pipeline runs.
- **Status_Badge**: A chip-style indicator showing run-level status (running, completed, failed, paused).
- **Citation_Chip**: A visual indicator showing whether a source citation is grounded or unverifiable.
- **Decision_Action**: An approve or reject operation submitted against a single queue item via POST /approval/items/{item_id}/decide.
- **Polling_Service**: A frontend service that fetches queue and run state from existing backend endpoints at a configurable interval.
- **Optimistic_Update**: A UI pattern where the local state reflects a decision immediately before server confirmation, with rollback on failure.
- **Queue_Item**: A single pending approval entry (finding, conflict, or proposed_update) as returned by the backend QueueItemResponse schema.
- **Source_Location**: A precise position within a document (page_number, section_id, start_offset, end_offset, clause_ref) associated with a queue item payload.

## Requirements

### Requirement 1: Queue List Display

**User Story:** As a compliance reviewer, I want to see all pending approval items for a selected run, so that I can understand the scope of work and choose which item to review next.

#### Acceptance Criteria

1. WHEN the reviewer selects a run from the Run_Selector, THE Review_Interface SHALL fetch the queue from GET /approval/runs/{run_id}/queue and display all items in the Queue_List.
2. THE Queue_List SHALL display each Queue_Item with its item_type (finding, conflict, or proposed_update), a summary derived from the payload, and a status chip (amber for pending, green for approved, red for rejected).
3. WHEN a Queue_Item payload contains source citations with a null source_span, THE Review_Interface SHALL render a Citation_Chip labeled "[citation unverifiable]" in muted gray.
4. WHEN a Queue_Item payload contains source citations with a valid source_span, THE Review_Interface SHALL render a Citation_Chip labeled with the clause_ref or page reference in standard text color.
5. THE Queue_List SHALL display the total item count and pending item count as returned by the QueueListResponse.

### Requirement 2: Queue Filtering and Sorting

**User Story:** As a compliance reviewer, I want to filter and sort the queue by type, severity, or unverifiable status, so that I can prioritize my review workflow.

#### Acceptance Criteria

1. THE Review_Interface SHALL provide filter controls that allow the reviewer to filter Queue_Items by item_type (finding, conflict, proposed_update).
2. THE Review_Interface SHALL provide a filter option to show only Queue_Items containing at least one unverifiable citation.
3. THE Review_Interface SHALL provide sort controls that allow the reviewer to sort Queue_Items by item_type or queued_at timestamp.
4. WHEN filters or sort criteria are applied, THE Queue_List SHALL update immediately using client-side filtering and sorting of the fetched data.

### Requirement 3: Detail View and Single-Item Decision

**User Story:** As a compliance reviewer, I want to inspect a single item in detail and approve or reject it with justification, so that I can make informed decisions on pipeline outputs.

#### Acceptance Criteria

1. WHEN the reviewer selects a Queue_Item from the Queue_List, THE Review_Interface SHALL fetch the full item from GET /approval/items/{item_id} and display its payload, all source citations with Source_Location details, and current status in the Detail_Panel.
2. THE Detail_Panel SHALL display an Approve button and a Reject button for items with pending status.
3. WHEN the reviewer clicks Approve or Reject, THE Review_Interface SHALL require the reviewer to provide a justification text before submission.
4. WHEN the reviewer submits a Decision_Action, THE Review_Interface SHALL send a POST request to /approval/items/{item_id}/decide with the decision value, reviewer_id, and justification.
5. WHEN the backend returns a successful DecisionResponse, THE Review_Interface SHALL update the item status in both the Detail_Panel and the Queue_List.
6. THE Detail_Panel SHALL hide the Approve and Reject buttons for items that have already been decided (status is approved or rejected).

### Requirement 4: Optimistic UI Updates

**User Story:** As a compliance reviewer, I want immediate visual feedback when I submit a decision, so that the interface feels responsive even under network latency.

#### Acceptance Criteria

1. WHEN the reviewer submits a Decision_Action, THE Review_Interface SHALL immediately update the local item status to the submitted decision value before receiving server confirmation.
2. IF the POST /approval/items/{item_id}/decide request fails, THEN THE Review_Interface SHALL rollback the local item status to pending and display an error notification to the reviewer.
3. WHILE an Optimistic_Update is in-flight, THE Review_Interface SHALL display a loading indicator on the affected Queue_Item.

### Requirement 5: Approval Gate Isolation

**User Story:** As a compliance reviewer, I want to be confident that approving or rejecting one item never affects any other item in the queue, so that my decisions are safe and independent.

#### Acceptance Criteria

1. WHEN the reviewer approves or rejects a Queue_Item, THE Review_Interface SHALL submit the decision for that single item only, without modifying or discarding other items in the queue.
2. THE Review_Interface SHALL maintain the full queue state for the selected run after each decision, updating only the decided item.
3. IF the backend returns HTTP 409 (item already decided), THEN THE Review_Interface SHALL refresh the item status from the server and display a notification that the item was already decided.

### Requirement 6: Run Progress Stepper

**User Story:** As a compliance reviewer, I want to see which pipeline stage is currently executing, so that I understand where the run stands and when items are expected to arrive in the queue.

#### Acceptance Criteria

1. THE Progress_Stepper SHALL display three stages: Understand, Examine, and Stay-Alive.
2. THE Progress_Stepper SHALL derive completion state exclusively from checkpointer data returned by the backend (current_node, completed_nodes, node_status fields from pipeline state).
3. WHEN a stage has all constituent nodes completed, THE Progress_Stepper SHALL mark that stage as complete with a visual checkmark.
4. WHEN a stage has at least one node currently running, THE Progress_Stepper SHALL mark that stage as in-progress with an animated indicator.
5. WHEN a stage has not started, THE Progress_Stepper SHALL mark that stage as pending with a muted visual treatment.

### Requirement 7: Run Selector and Status Badge

**User Story:** As a compliance reviewer, I want to switch between runs and see each run's overall status, so that I can manage multiple concurrent reviews.

#### Acceptance Criteria

1. THE Run_Selector SHALL allow the reviewer to select from available pipeline runs.
2. WHEN the reviewer switches runs, THE Review_Interface SHALL clear the current queue state and fetch the new run's queue and progress data.
3. THE Status_Badge SHALL display the selected run's current status (running, completed, failed, paused) adjacent to the Run_Selector.
4. THE Review_Interface SHALL ensure that queue items displayed belong exclusively to the selected run, preventing cross-run contamination.

### Requirement 8: Polling and Data Freshness

**User Story:** As a compliance reviewer, I want the queue and progress to stay current without manual refresh, so that I see newly queued items and status changes from other reviewers promptly.

#### Acceptance Criteria

1. THE Polling_Service SHALL fetch GET /approval/runs/{run_id}/queue at a configurable interval (default 10 seconds) while the Review_Interface is active.
2. THE Polling_Service SHALL fetch run progress state at the same configurable interval.
3. WHEN polling returns updated data, THE Review_Interface SHALL merge the new data into the displayed queue without disrupting the reviewer's current selection or scroll position.
4. WHEN the browser tab loses focus, THE Polling_Service SHALL pause polling to reduce unnecessary network requests.
5. WHEN the browser tab regains focus, THE Polling_Service SHALL immediately fetch fresh data and resume the polling interval.

### Requirement 9: Keyboard Navigation and Accessibility

**User Story:** As a compliance reviewer, I want to navigate the interface entirely with a keyboard and have proper screen reader support, so that the tool is accessible to all team members.

#### Acceptance Criteria

1. THE Review_Interface SHALL provide keyboard navigation to move between Queue_Items in the Queue_List using arrow keys.
2. THE Review_Interface SHALL provide keyboard shortcuts to focus the Approve and Reject buttons from the Detail_Panel.
3. THE Review_Interface SHALL apply ARIA labels to all interactive elements including the Queue_List, Detail_Panel, decision buttons, filter controls, and the Progress_Stepper.
4. THE Review_Interface SHALL manage focus: when a decision is submitted, focus SHALL move to the next pending item in the Queue_List.
5. THE Review_Interface SHALL support a visible focus ring on all focusable elements that meets WCAG 2.1 AA contrast requirements.

### Requirement 10: Visual Design and Responsiveness

**User Story:** As a compliance reviewer, I want a professional, distraction-free interface that works on my laptop and tablet, so that I can review documents comfortably in different contexts.

#### Acceptance Criteria

1. THE Review_Interface SHALL use a deep navy and charcoal color palette with high-contrast text meeting WCAG 2.1 AA contrast ratios.
2. THE Review_Interface SHALL render in a master-detail split layout: Queue_List on the left, Detail_Panel on the right.
3. WHEN the viewport width is below 768px, THE Review_Interface SHALL collapse the master-detail layout into a single-column stacked view with navigation between list and detail.
4. THE Review_Interface SHALL display status chips using the defined color scheme: amber for pending, green for approved, red for rejected, muted gray for unverifiable.
5. THE Review_Interface SHALL render within the existing multi-page app shell as a route managed by React Router.

### Requirement 11: Resume After Kill/Restart

**User Story:** As a compliance reviewer, I want previously submitted decisions to persist and the queue to be accurate after a backend kill/restart, so that my work is never lost.

#### Acceptance Criteria

1. WHEN the backend restarts after a kill, THE Review_Interface SHALL recover correct queue state by polling GET /approval/runs/{run_id}/queue, reflecting all previously committed decisions.
2. WHEN the reviewer triggers a run resume via POST /runs/{run_id}/resume, THE Review_Interface SHALL update the Progress_Stepper and Status_Badge to reflect the resumed state.
3. IF the Polling_Service receives a network error during a fetch, THEN THE Review_Interface SHALL display a connection-lost indicator and retry on the next polling interval without discarding local state.

### Requirement 12: Integration Tests

**User Story:** As a developer, I want Playwright smoke tests covering the approve/reject flow and the kill/restart resume path, so that regressions in the review interface are caught automatically.

#### Acceptance Criteria

1. THE test suite SHALL include a Playwright test that navigates to the Review_Interface, selects a run, selects a pending item, submits an approve decision with justification, and verifies the item status updates to approved.
2. THE test suite SHALL include a Playwright test that navigates to the Review_Interface, selects a run, submits a reject decision, and verifies the item status updates to rejected without affecting other queue items.
3. THE test suite SHALL include a Playwright test that simulates a backend restart (stop/start mock server), triggers a resume, and verifies previously submitted decisions remain intact and the progress stepper reflects the resumed state.
