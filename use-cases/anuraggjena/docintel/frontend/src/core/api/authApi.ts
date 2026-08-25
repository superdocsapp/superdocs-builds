import { authClient } from './client'

// User interface matching backend User model
export interface User {
  id: string
  email: string
  name: string
  role: 'user' | 'reviewer' | 'admin'
  is_active: boolean
  created_at: string
  updated_at: string
}

// Auth response from login/register endpoints
export interface AuthResponse {
  user: User
  access_token: string
  token_type: 'bearer'
}

// Refresh token response
interface RefreshResponse {
  access_token: string
  token_type: 'bearer'
}

// Stream token response
export interface StreamTokenResponse {
  stream_token: string
  token_type: 'stream'
  expires_in: number
}

/**
 * Auth API client functions
 * Handles authentication operations with the backend
 */
export const authApi = {
  /**
   * Login user with email and password
   * Sets refresh token in httpOnly cookie (managed by backend)
   * Returns access token for in-memory storage
   */
  login: async (email: string, password: string): Promise<AuthResponse> => {
    const response = await authClient.post<AuthResponse>(
      '/auth/login',
      { email, password }
    )
    return response.data
  },

  /**
   * Register new user account
   * Sets refresh token in httpOnly cookie (managed by backend)
   * Returns access token for in-memory storage
   */
  register: async (email: string, password: string, name: string): Promise<AuthResponse> => {
    const response = await authClient.post<AuthResponse>(
      '/auth/register',
      { email, password, name }
    )
    return response.data
  },

  /**
   * Logout current user
   * Clears refresh token cookie on backend
   */
  logout: async (): Promise<void> => {
    await authClient.post('/auth/logout', {})
  },

  /**
   * Get current user info
   * Requires valid access token in Authorization header
   */
  getMe: async (accessToken: string): Promise<User> => {
    const response = await authClient.get<User>(
      '/auth/me',
      {
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      }
    )
    return response.data
  },

  /**
   * Refresh access token using httpOnly refresh token cookie
   * Backend validates refresh token and issues new access token
   * Returns new access token for in-memory storage
   */
  refresh: async (): Promise<string> => {
    const response = await authClient.post<RefreshResponse>(
      '/auth/refresh',
      {}
    )
    return response.data.access_token
  },

  /**
   * Create a short-lived stream token for SSE workflow streaming
   * Requires valid access token in Authorization header
   * Stream tokens are scoped to specific workflow run and expire in 60 seconds
   */
  createStreamToken: async (runId: string, accessToken: string): Promise<string> => {
    const response = await authClient.post<StreamTokenResponse>(
      '/auth/stream-token',
      { run_id: runId },
      {
        headers: {
          Authorization: `Bearer ${accessToken}`
        }
      }
    )
    return response.data.stream_token
  }
}
