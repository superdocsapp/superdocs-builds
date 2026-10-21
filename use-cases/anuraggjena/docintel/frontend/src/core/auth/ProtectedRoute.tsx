import React from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'

interface ProtectedRouteProps {
  children: React.ReactNode
}

export function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { status } = useAuth()
  const location = useLocation()

  if (status === 'loading') {
    // AuthGate already handles loading state
    return null
  }

  if (status === 'unauthenticated') {
    // Redirect to login with return URL
    const returnTo = encodeURIComponent(location.pathname + location.search)
    return <Navigate to={`/login?returnTo=${returnTo}`} replace />
  }

  return <>{children}</>
}
