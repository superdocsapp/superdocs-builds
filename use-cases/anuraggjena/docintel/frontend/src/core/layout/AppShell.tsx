import { useState, type ReactNode } from 'react'
import { Menu } from 'lucide-react'

import { Button } from '@/shared/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from '@/shared/components/ui/sheet'
import { LiveConnectionProvider } from './LiveConnectionContext'
import { Sidebar, SidebarNav } from './Sidebar'

interface AppShellProps {
  children: ReactNode
}

function AppShellInner({ children }: AppShellProps) {
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  return (
    <div className="flex min-h-screen bg-[#F8FAFC] text-slate-900 font-sans antialiased selection:bg-blue-100 selection:text-blue-900">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile-only menu button */}
        <div className="md:hidden flex items-center justify-between px-4 py-3 bg-white border-b border-slate-200">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-slate-600"
            onClick={() => setMobileNavOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </Button>
          <span className="text-xs font-bold text-slate-800 tracking-tight">DocIntel</span>
          <div className="w-8" />
        </div>

        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-[1400px] px-6 sm:px-8 lg:px-10 py-6 sm:py-8">{children}</div>
        </main>
      </div>

      {/* Mobile Drawer */}
      <Sheet open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
        <SheetContent side="left" className="w-64 p-4">
          <SheetHeader className="border-b px-2 pb-3 mb-2 text-left">
            <SheetTitle className="text-base font-bold text-slate-900">Navigation</SheetTitle>
          </SheetHeader>
          <SidebarNav onNavigate={() => setMobileNavOpen(false)} />
        </SheetContent>
      </Sheet>
    </div>
  )
}

export function AppShell({ children }: AppShellProps) {
  return (
    <LiveConnectionProvider>
      <AppShellInner>{children}</AppShellInner>
    </LiveConnectionProvider>
  )
}


