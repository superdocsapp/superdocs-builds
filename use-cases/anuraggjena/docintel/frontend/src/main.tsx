import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import App from './App'
import './index.css'
import { AuthProvider, AuthGate, useAuth } from './core/auth'
import { setAccessTokenGetter, setAccessTokenSetter, setLogoutHandler } from './core/api/client'
import { ErrorBoundary } from './core/components/ErrorBoundary'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60 * 1000,
      retry: 1,
      refetchOnWindowFocus: false
    }
  }
})

// Wire auth context to API client interceptors
function AuthContextWiring({ children }: { children: React.ReactNode }) {
  const { accessToken, logout, setAccessToken } = useAuth()

  // Wire synchronously so first authenticated API requests include the token.
  setAccessTokenGetter(() => accessToken)
  setAccessTokenSetter(setAccessToken)
  setLogoutHandler(logout)

  return <>{children}</>
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <AuthProvider>
            <AuthContextWiring>
              <AuthGate>
                <App />
              </AuthGate>
            </AuthContextWiring>
          </AuthProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
)
