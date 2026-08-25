import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Menu, ChevronRight } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'

import { workspaceApi } from '@/core/api/client'
import { Button } from '@/shared/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/shared/components/ui/sheet'
import { LiveIndicator, type LiveIndicatorState } from './LiveIndicator'
import { SidebarNav } from './Sidebar'
import { UserMenu } from './UserMenu'

interface TopbarProps {
  liveIndicatorState?: LiveIndicatorState
}

export function Topbar({ liveIndicatorState = 'hidden' }: TopbarProps) {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  const { data: workspace } = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId,
  })

  return (
    <>
      <header className="h-14 shrink-0 border-b border-slate-200/80 bg-white px-6 sm:px-8 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button
            variant="ghost"
            size="icon"
            className="md:hidden -ml-2 h-8 w-8 text-slate-600"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </Button>

          {/* Breadcrumb navigation */}
          <nav className="flex items-center text-sm" aria-label="Breadcrumb">
            <Link
              to="/workspaces"
              className="text-slate-500 hover:text-slate-900 transition-colors font-normal"
            >
              All Workspaces
            </Link>
            {workspace && (
              <>
                <ChevronRight className="w-3.5 h-3.5 text-slate-400 mx-2 shrink-0" />
                <span className="text-slate-900 font-medium truncate max-w-[280px]">
                  {workspace.name}
                </span>
              </>
            )}
          </nav>
        </div>

        <div className="flex items-center gap-4">
          <LiveIndicator state={liveIndicatorState} />
          <UserMenu />
        </div>
      </header>

      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-64 p-4">
          <SheetHeader className="border-b px-2 pb-3 mb-2 text-left">
            <SheetTitle className="text-base font-bold text-slate-900">Navigation</SheetTitle>
          </SheetHeader>
          <SidebarNav onNavigate={() => setMobileNavOpen(false)} />
        </SheetContent>
      </Sheet>
    </>
  )
}


