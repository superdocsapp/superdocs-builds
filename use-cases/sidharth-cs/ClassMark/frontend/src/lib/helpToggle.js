// Pure toggle state machine for the Help/About popover — testable without
// a DOM. The component dispatches events; the reducer owns the single
// authoritative open/closed state.

export const INITIAL_HELP_STATE = { open: false }

// Events:
//   { type: 'button-click' }          — the ? button itself
//   { type: 'outside-pointerdown' }   — pointer down outside button+popover
//   { type: 'escape' }                — Escape key
export function helpToggle(state, event) {
  switch (event.type) {
    case 'button-click':
      return { open: !state.open }
    case 'outside-pointerdown':
    case 'escape':
      // Outside clicks and Escape only ever close — never reopen.
      return state.open ? { open: false } : state
    default:
      return state
  }
}
