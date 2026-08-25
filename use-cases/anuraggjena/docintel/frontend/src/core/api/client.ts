import axios, { AxiosHeaders } from 'axios'
import type { Workspace, CreateWorkspaceRequest, UpdateWorkspaceRequest } from './types'

export const apiClient = axios.create({
  baseURL: '/api/v1',
  withCredentials: true, // Enable cookies for all requests
})

// Separate axios instance for auth endpoints to prevent interceptor recursion
const authClient = axios.create({
  baseURL: '/api/v1',
  headers: {
    'Content-Type': 'application/json'
  },
  withCredentials: true
})

// Request interceptor: inject access token
let getAccessToken: (() => string | null) | null = null
let setAccessToken: ((token: string | null) => void) | null = null

export function setAccessTokenGetter(getter: () => string | null) {
  getAccessToken = getter
}

export function setAccessTokenSetter(setter: (token: string | null) => void) {
  setAccessToken = setter
}

apiClient.interceptors.request.use(
  (config) => {
    if (getAccessToken) {
      const token = getAccessToken()
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }

    const headers = AxiosHeaders.from(config.headers)
    if (config.data instanceof FormData) {
      headers.delete('Content-Type')
      headers.delete('content-type')
    } else if (
      config.data !== undefined &&
      config.data !== null &&
      typeof config.data !== 'string' &&
      !headers.has('Content-Type')
    ) {
      headers.set('Content-Type', 'application/json')
    }
    config.headers = headers
    return config
  },
  (error) => Promise.reject(error)
)

// Response interceptor: handle token refresh on 401
let refreshPromise: Promise<string> | null = null
let onLogout: (() => void) | null = null

export function setLogoutHandler(handler: () => void) {
  onLogout = handler
}

// Helper to check if URL is an auth endpoint
function isAuthEndpoint(url?: string): boolean {
  if (!url) return false
  return url.includes('/auth/login') ||
         url.includes('/auth/register') ||
         url.includes('/auth/refresh') ||
         url.includes('/auth/logout')
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config

    // Skip refresh logic for auth endpoints to prevent recursion
    if (isAuthEndpoint(originalRequest.url)) {
      return Promise.reject(error)
    }

    // Handle 401 Unauthorized (access token expired)
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true

      try {
        // Prevent concurrent refresh requests
        if (!refreshPromise) {
          refreshPromise = (async () => {
            try {
              const { authApi } = await import('./authApi')
              const newToken = await authApi.refresh()

              // Update token in auth context state
              if (setAccessToken) {
                setAccessToken(newToken)
              }

              refreshPromise = null
              return newToken
            } catch (refreshError) {
              refreshPromise = null
              throw refreshError
            }
          })()
        }

        const newToken = await refreshPromise

        // Update Authorization header for retry
        originalRequest.headers.Authorization = `Bearer ${newToken}`

        // Retry original request with new token
        return apiClient(originalRequest)
      } catch (refreshError) {
        // Refresh failed - logout user
        if (onLogout) {
          onLogout()
        }
        return Promise.reject(refreshError)
      }
    }

    // Don't retry 403 (permission error, not auth error)
    return Promise.reject(error)
  }
)

// Export auth client for use by authApi to prevent interceptor recursion
export { authClient }

export const workspaceApi = {
  list: async (): Promise<Workspace[]> => {
    const response = await apiClient.get<Workspace[]>('/workspaces')
    // Backend filters by authenticated user automatically
    return response.data
  },

  get: async (id: string): Promise<Workspace> => {
    const response = await apiClient.get<Workspace>(`/workspaces/${id}`)
    return response.data
  },

  create: async (data: CreateWorkspaceRequest): Promise<Workspace> => {
    const response = await apiClient.post<Workspace>('/workspaces', data)
    return response.data
  },

  update: async (id: string, data: UpdateWorkspaceRequest): Promise<Workspace> => {
    const response = await apiClient.patch<Workspace>(`/workspaces/${id}`, data)
    return response.data
  },

  delete: async (id: string): Promise<void> => {
    await apiClient.delete(`/workspaces/${id}`)
  }
}
