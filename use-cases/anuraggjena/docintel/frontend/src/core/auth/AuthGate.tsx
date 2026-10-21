import React from 'react'
import { useAuth } from './AuthContext'
import { Skeleton } from '@/shared/components/ui/skeleton'

/**
 * AuthGate component props
 */
export interface AuthGateProps {
  children: React.ReactNode
}

/**
 * AuthGate component
 * Shows loading screen while authentication status is being determined.
 * Once loaded, renders the children.
 */
export const AuthGate: React.FC<AuthGateProps> = ({ children }) => {
  const { status } = useAuth()

  if (status === 'loading') {
    return (
      <div className="flex min-h-screen items-center justify-center bg-muted/40">
        <div className="w-full max-w-xs space-y-4 p-4" aria-label="Loading application">
          <Skeleton className="mx-auto h-8 w-32" />
          <Skeleton className="mx-auto h-4 w-48" />
          <Skeleton className="h-10 w-full rounded-md" />
        </div>
      </div>
    )
  }

  return <>{children}</>
}
