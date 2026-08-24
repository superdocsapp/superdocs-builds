# DocRelay UI direction

Status: accepted and implemented for the production UI phase.

## Visual thesis

DocRelay is a change-and-proof workbench, not a document editor. The interface should make a simple promise visible: AI proposes; a human decides; DocRelay proves the write is safe. The tone is quiet, technical, precise, and trustworthy.

The signature visual is a thin verification line with small square checkpoints. Deep pine marks selected, approved, and verified states. Amber is reserved for conflicts. Document text appears only when the API truthfully provides it, primarily as old/new proposal text.

## Layout system

- Desktop: restrained 180–220px primary navigation, dominant work area, and an optional 260–300px proof rail for evidence-heavy states.
- Empty source selection uses the full work area and keeps Google Picker central.
- Selected-document states use a compact identity strip, a thin workflow line, and an open change/proof workbench.
- Review uses a small proposal index plus a dominant old/new diff; it never renders a fake page.
- Watch uses an open folder-rule rail and independent document-run rows, separated by fine rules rather than nested cards.
- Mobile replaces the sidebar with bottom navigation, stacks before/after, collapses secondary evidence, and keeps decisions in a sticky safe-area footer.

## Typography hierarchy

- UI family: Geist/Inter-style sans serif with system fallbacks.
- Reader family: Source Serif 4, used **only** inside `.document-page`. The
  frozen preview is the one surface in the product that is a document rather
  than product chrome, so it is set in a text face. All chrome around it — the
  document toolbar included — stays in the UI family.
- Hero title: 32–36px, 600 weight, −0.038em tracking.
- Page title: 26px, 600 weight.
- Section title: 15–17px, 600 weight.
- Body: 14–16px with generous 1.6 line height.
- Controls and navigation: deliberate 13–15px sizing; never browser-default typography.
- Revisions, hashes, and IDs: compact monospace, visually subordinate.
- Small uppercase labels stay at or above 4.5:1 contrast on every surface they
  are used on; `--muted-soft` is tuned to that limit, not below it.

## Surface hierarchy

- A warm-neutral ladder, lifted rather than sepia: sidebar → working canvas →
  conversation → document canvas → paper, with cards a half-step above the
  surface they sit on. Cards and paper are true white; the canvas between and
  behind panes carries the warmth.
- Text: warm charcoal; muted copy: warm gray. Borders: `--border` for controls,
  `--border-light` for pane edges, `--border-hair` for rules inside a pane.
- Radius: 14px panes, 12px cards, 9–10px controls, 18px plates, 6px document
  page. Rows and open sections usually have no enclosing radius.
- Shadows: warm-tinted and low-contrast. `--shadow-subtle` for flat surfaces,
  `--shadow-raised` for cards, `--shadow-pane` for panes, `--shadow-lifted` for
  the one focal plate per screen, `--shadow-document` for the page.
- Accent: deep pine for primary actions, selection and verified state; tinted
  before/after evidence bands for diffs, with a stronger token tint on the exact
  mutated span only; amber for conflict.
- One pill geometry (`.pill` + tone) for every small state label, so a state
  reads the same in a conversation header, a table row and a page header.

## Spacing principles

- Use a 4px base scale with 8/12/16/24/32/48px steps.
- Prefer clear bands and alignment over decorative containers.
- Keep operational rows compact but give headings and primary decisions breathing room.
- Avoid both cramped sidebars and large unused dashboard voids.

## Interaction hierarchy

1. Current workflow action: Prepare change, Approve, Write back safely, Review latest.
2. Safe alternatives: Reject, Cancel write-back, Return to watch run.
3. Evidence disclosure: technical IDs and provider payloads stay collapsed until requested.
4. Navigation and source changes remain quiet and do not compete with the current decision.

Focus is always visible. Loading replaces action text without shifting layout. Disabled states explain why when the reason is not obvious. Motion is limited to small status and panel transitions and respects reduced-motion preferences.

Progress is drawn as a vertical rail with round marks, shared by the import
sequence, the run's processing steps and the safety check. The active mark
breathes on a slow opacity cycle rather than blinking, and skeletons use one
slow light sweep (`.sheen`), so a screen that is working never flickers.

## State treatment

- Processing: truthful ordered stages, no percentages.
- Awaiting review: neutral current state; every proposal needs an explicit decision.
- Dry-run ready: proof ledger plus an explicit “No cloud write has happened yet.”
- Write authorization required: neutral permission checkpoint for one exact file, never an error.
- Conflict: amber safe stop; state that nothing was overwritten and show only revisions/evidence actually known.
- Unknown external effect: distinct attention state with no generic retry promise.
- Verified success: restrained finality led by backup, revision, and structural-verification evidence.
- Watch scan: every document is independently actionable; one conflict never visually contaminates sibling runs.

## Deliberately avoid

- Fake document pages, editor chrome, invented body content, or a decorative empty canvas.
- Marketing heroes, AI gradients, glass, bento grids, metric tiles, charts, or decorative badges.
- Card-inside-card layouts beyond one level, oversized radii, heavy shadows,
  and status communicated by color alone.
- Placeholder navigation such as Settings, Billing, Analytics, or account administration.
- Hardcoded production documents, rules, scans, or run history.

## Data truth notes

The current contracts support document identity/revision, proposal old/new text, structural location, dry-run proof, write outcomes, watch roots/scans/items, and per-run summaries. They do not expose a truthful full-document preview, so none is designed.

The implementation exposes the already-persisted watch-rule `configuration.folder_name` and a read-only global owned-run index. These additions only support truthful labels/history and do not change workflow semantics. Full document body content is still intentionally absent because no current contract proves a complete read-only preview.

## Implemented component inventory

- Product shell with Workspace, Watch, and Runs only; a collapsible rail whose
  collapsed header is the brand mark until hovered, when it becomes the expand
  control.
- Central Drive source selection, compact document identity, and instruction workbench.
- Shared workflow progress, proposal diff, status, notice, safety-check, and skeleton primitives.
- Hero dry-run, conflict, exact-file authorization, unknown-effect, and verified-success states.
- Watch root/schedule/rule workspace plus independent per-document scan runs.
- Global run history and resumable run-detail rendering against durable backend state.
