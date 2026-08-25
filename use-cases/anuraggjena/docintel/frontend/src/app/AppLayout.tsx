import { useEffect } from 'react'
import { Outlet, useParams } from 'react-router-dom'

import { AppShell } from '@/core/layout/AppShell'

const LAST_WORKSPACE_KEY = 'lastWorkspaceId'

export function AppLayout() {
  const { workspaceId } = useParams<{ workspaceId: string }>()

  useEffect(() => {
    if (workspaceId) {
      sessionStorage.setItem(LAST_WORKSPACE_KEY, workspaceId)
    }
  }, [workspaceId])

  return (
    <AppShell>
      <Outlet />
    </AppShell>
  )
}
