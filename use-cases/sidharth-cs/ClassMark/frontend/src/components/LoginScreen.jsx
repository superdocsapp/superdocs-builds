// Entry point. Properly centered; one obvious primary action.
export default function LoginScreen({ error }) {
  return (
    <div className="login-screen">
      <div className="login-card">
        <div className="brand brand-center">
          <span className="brand-mark brand-mark-lg" aria-hidden="true">C</span>
          <span className="brand-name brand-name-lg">Classmark</span>
        </div>
        <p className="login-tagline">AI-assisted document feedback for Google Classroom</p>
        <p className="login-blurb">
          Review student work with targeted, sentence-level suggestions —
          approve or reject each proposed change, then return the reviewed
          document to the same Classroom submission.
        </p>
        <a className="btn btn-primary btn-lg btn-google" href="/api/auth/login">
          <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
            <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"/>
            <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/>
            <path fill="#FBBC05" d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18A10.97 10.97 0 0 0 1 12c0 1.77.43 3.45 1.18 4.94l3.66-2.84z"/>
            <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"/>
          </svg>
          Continue with Google
        </a>
        <p className="login-note">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
          </svg>
          Secure Google Classroom access
        </p>
        {error && (
          <div className="error-banner" role="alert">
            <strong>Sign-in unavailable</strong>
            <p>{error}</p>
          </div>
        )}
      </div>
    </div>
  )
}
