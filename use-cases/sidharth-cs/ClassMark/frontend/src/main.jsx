import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './styles.css'

// Defensive application-level error boundary: a render exception must
// never produce a blank page — it shows a recoverable error instead.
// The underlying bug is still fixed at its source; this only keeps the
// app usable if something unexpected slips through.
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="boot-screen" role="alert">
          <div className="login-card">
            <h1>Classmark hit an unexpected problem</h1>
            <p className="muted">
              Reload the page to try again. If it persists, check that the
              server is running.
            </p>
            <button type="button" className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
)
