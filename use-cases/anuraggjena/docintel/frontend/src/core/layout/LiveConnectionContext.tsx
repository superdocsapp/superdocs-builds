import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import type { LiveIndicatorState } from './LiveIndicator'

interface LiveConnectionContextValue {
  state: LiveIndicatorState
  setState: (state: LiveIndicatorState) => void
}

const LiveConnectionContext = createContext<LiveConnectionContextValue | null>(null)

export function LiveConnectionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveIndicatorState>('hidden')
  const value = useMemo(() => ({ state, setState }), [state])

  return (
    <LiveConnectionContext.Provider value={value}>{children}</LiveConnectionContext.Provider>
  )
}

export function useLiveConnection(): LiveConnectionContextValue {
  const context = useContext(LiveConnectionContext)
  if (!context) {
    throw new Error('useLiveConnection must be used within LiveConnectionProvider')
  }
  return context
}

export function useSetLiveConnection(state: LiveIndicatorState) {
  const { setState } = useLiveConnection()

  useEffect(() => {
    setState(state)
    return () => setState('hidden')
  }, [state, setState])
}
