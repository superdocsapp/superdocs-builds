import React, { createContext, useContext, useState, useEffect, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { authApi, User } from '../api/authApi'

// Shared promise to prevent concurrent session restoration (StrictMode double-mount)
let sessionRestorePromise: Promise<{ user: User; token: string } | null> | null = null

/**
 * Authentication status enum
 */
export type AuthStatus = 'loading' | 'authenticated' | 'unauthenticated'

/**
 * Authentication context value
 * Provides user state, access token, and auth actions
 */
export interface AuthContextValue {
  user: User | null
  accessToken: string | null
  status: AuthStatus
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, name: string) => Promise<void>
  logout: () => Promise<void>
  setAccessToken: (token: string | null) => void
}

/**
 * Authentication context
 * Provides auth state and actions to components
 */
const AuthContext = createContext<AuthContextValue | undefined>(undefined)

/**
 * Hook to access auth context
 * Throws if used outside AuthProvider
 */
export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

/**
 * Authentication provider component
 * Manages auth state and provides it to child components
 */
export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const navigate = useNavigate()

  // Auth state
  const [user, setUser] = useState<User | null>(null)
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [status, setStatus] = useState<AuthStatus>('loading')

  /**
   * Session restoration on mount
   * Attempts to restore session using refresh cookie
   * Deduplicates concurrent calls to prevent StrictMode double-mount issues
   */
  useEffect(() => {
    let cancelled = false

    const restoreSession = async () => {
      try {
        // Share promise across concurrent mounts (StrictMode)
        if (!sessionRestorePromise) {
          sessionRestorePromise = (async () => {
            try {
              // Get access token via refresh
              const token = await authApi.refresh()

              // Pass token explicitly to getMe to avoid race condition
              const user = await authApi.getMe(token)

              return { user, token }
            } catch (error) {
              // No valid refresh cookie or session expired
              sessionRestorePromise = null
              return null
            }
          })()
        }

        const result = await sessionRestorePromise
        sessionRestorePromise = null // Clear for next mount

        if (cancelled) return

        if (result) {
          setUser(result.user)
          setAccessToken(result.token)
          setStatus('authenticated')
        } else {
          setStatus('unauthenticated')
        }
      } catch {
        if (cancelled) return
        setStatus('unauthenticated')
      }
    }

    restoreSession()

    return () => {
      cancelled = true
    }
  }, [])

  /**
   * Login user
   * Sets user and access token
   */
  const login = useCallback(async (email: string, password: string) => {
    const response = await authApi.login(email, password)
    setUser(response.user)
    setAccessToken(response.access_token)
    setStatus('authenticated')
  }, [])

  /**
   * Register new user
   * Sets user and access token
   */
  const register = useCallback(async (email: string, password: string, name: string) => {
    const response = await authApi.register(email, password, name)
    setUser(response.user)
    setAccessToken(response.access_token)
    setStatus('authenticated')
  }, [])

  /**
   * Logout user
   * Clears state, calls logout endpoint, and navigates to login
   */
  const logout = useCallback(async () => {
    try {
      await authApi.logout()
    } catch (error) {
      // Continue with logout even if API call fails
      console.error('Logout API call failed:', error)
    } finally {
      // Always clear local state and navigate
      setUser(null)
      setAccessToken(null)
      setStatus('unauthenticated')
      navigate('/login')
    }
  }, [navigate])

  /**
   * Wrapper for setAccessToken to match type signature
   */
  const updateAccessToken = useCallback((token: string | null) => {
    setAccessToken(token)
  }, [])

  const value: AuthContextValue = useMemo(
    () => ({
      user,
      accessToken,
      status,
      login,
      register,
      logout,
      setAccessToken: updateAccessToken
    }),
    [user, accessToken, status, login, register, logout, updateAccessToken]
  )

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  )
}
