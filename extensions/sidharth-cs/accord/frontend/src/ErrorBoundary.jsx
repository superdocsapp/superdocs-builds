import { Component } from 'react'

// Zoom's own panel host swaps in an opaque "Something went wrong" screen
// (a fresh incident id every time, no diagnostic value to us) the instant
// any render throws uncaught. This boundary is the only thing standing
// between a bug here and that dead end — it can't fix the crash, but it
// can make the crash legible: the real error text stays on screen instead
// of vanishing into Zoom's own crash reporter. React requires a class
// component for getDerivedStateFromError/componentDidCatch; no hook
// equivalent exists.
export class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    // console survives even though the render tree doesn't — the one
    // place a stack trace might still reach us if devtools are ever
    // available (they usually aren't inside the Zoom panel webview).
    console.error('[ErrorBoundary]', error, info?.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="crash">
        <div className="crash-brand">ACCORD</div>
        <p className="crash-title">Something went wrong in the panel.</p>
        <p className="crash-detail">{String(this.state.error?.message || this.state.error)}</p>
        <button className="btn primary" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    )
  }
}
