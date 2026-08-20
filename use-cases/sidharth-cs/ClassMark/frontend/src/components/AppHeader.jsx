// Classmark header: brand mark, authenticated teacher identity (text
// only), Help popover, sign out. Help and sign-out are independent
// controls — the popover never touches workflow or auth state.
//
// Toggle correctness: one authoritative open/closed state lives in the
// helpToggle reducer. The outside-click handler ignores any pointer down
// inside the button+popover wrapper, so clicking the ? button itself can
// never be mistaken for an outside click (that was the old flicker/reopen
// bug: mousedown closed it, then the click reopened it).
import { useEffect, useReducer, useRef } from 'react'
import { helpToggle, INITIAL_HELP_STATE } from '../lib/helpToggle.js'
import HelpPopover from './HelpPopover.jsx'

export default function AppHeader({ email, onSignOut, busy }) {
  const [help, dispatch] = useReducer(helpToggle, INITIAL_HELP_STATE)
  const helpWrapRef = useRef(null)
  const helpButtonRef = useRef(null)
  const panelRef = useRef(null)

  // Outside click and Escape handling while open.
  useEffect(() => {
    if (!help.open) return
    function onPointerDown(e) {
      const wrap = helpWrapRef.current
      if (wrap && wrap.contains(e.target)) return // button/popover — never outside
      dispatch({ type: 'outside-pointerdown' })
    }
    function onKeyDown(e) {
      if (e.key === 'Escape') dispatch({ type: 'escape' })
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [help.open])

  // When the popover closes, return focus to the trigger if focus was in
  // the popover (outside-click and Escape paths).
  useEffect(() => {
    if (!help.open && document.activeElement === panelRef.current && helpButtonRef.current) {
      helpButtonRef.current.focus()
    }
  }, [help.open])

  return (
    <header className="app-header">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">C</span>
        <span className="brand-name">Classmark</span>
      </div>
      <div className="header-right">
        {email && <span className="teacher-email">{email}</span>}
        <span className="help-wrap" ref={helpWrapRef}>
          <button
            ref={helpButtonRef}
            type="button"
            className="help-button"
            aria-label="Help and workflow information"
            aria-haspopup="dialog"
            aria-expanded={help.open}
            aria-controls="help-popover"
            onClick={() => dispatch({ type: 'button-click' })}
          >
            ?
          </button>
          <HelpPopover open={help.open} onClose={() => dispatch({ type: 'escape' })} panelRef={panelRef} />
        </span>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          onClick={onSignOut}
          disabled={busy}
        >
          Sign out
        </button>
      </div>
    </header>
  )
}
