import { Link, NavLink, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  LayoutGrid,
  FileText,
  GitBranch,
  ClipboardCheck,
  BookOpen,
  Settings,
  LogOut,
  Film,
  Files,
  FolderDown,
  type LucideIcon,
} from 'lucide-react'

import { cn } from '@/lib/utils'
import { useAuth } from '@/core/auth'
import { workspaceApi } from '@/core/api/client'
import { reviewApi } from '@/core/api/reviewApi'
import { DocIntelLogo } from '@/features/auth/AuthLayout'
import { WorkspaceSelector } from './WorkspaceSelector'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  end?: boolean
  isAbsolute?: boolean
}

const TARIFF_NAV_ITEMS: NavItem[] = [
  { to: '', label: 'Overview', icon: LayoutGrid, end: true },
  { to: 'documents', label: 'Documents', icon: FileText },
  { to: 'runs', label: 'Workflow Runs', icon: GitBranch },
  { to: 'reviews', label: 'Reviews', icon: ClipboardCheck },
  { to: 'knowledge', label: 'Knowledge', icon: BookOpen },
  { to: 'settings', label: 'Settings', icon: Settings },
]

const SCREENPLAY_NAV_ITEMS: NavItem[] = [
  { to: '', label: 'Screenplay', icon: Film, end: true },
  { to: 'screenplays', label: 'My Screenplays', icon: Files },
  { to: 'reviews', label: 'Reviews', icon: ClipboardCheck },
  { to: 'exports', label: 'Exports', icon: FolderDown },
  { to: 'settings', label: 'Settings', icon: Settings },
]

interface SidebarNavProps {
  onNavigate?: () => void
  className?: string
}

export function SidebarNav({ onNavigate, className }: SidebarNavProps) {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { user, logout, accessToken } = useAuth()
  const basePath = workspaceId ? `/workspace/${workspaceId}` : ''

  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const reviewsQuery = useQuery({
    queryKey: ['reviews', workspaceId],
    queryFn: () => reviewApi.listWorkspaceReviews(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const isScreenplay = workspaceQuery.data?.workflow_type === 'screenplay'
  const navItems = isScreenplay ? SCREENPLAY_NAV_ITEMS : TARIFF_NAV_ITEMS

  const pendingReviewsCount = (reviewsQuery.data ?? []).filter((r) =>
    ['in_review', 'pending', 'awaiting_review', 'waiting'].includes(r.status)
  ).length

  const linkClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      'flex items-center justify-between rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150',
      isActive
        ? 'bg-blue-50 text-blue-600 font-semibold shadow-xs'
        : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900'
    )

  const initials = user?.name
    ? user.name
        .split(' ')
        .map((n) => n[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : (user?.email?.[0] || 'U').toUpperCase()

  return (
    <div className={cn('flex flex-col justify-between h-full', className)}>
      <div className="space-y-6">
        {/* Logo */}
        <div className="px-2 pt-1">
          <Link to="/workspaces">
            <DocIntelLogo />
          </Link>
        </div>

        {/* Workspace Selector */}
        <div className="px-1">
          <WorkspaceSelector />
        </div>

        {/* Navigation Items */}
        <nav className="flex flex-col gap-1 px-1">
          {navItems.map(({ to, label, icon: Icon, end, isAbsolute }) => {
            const targetPath = isAbsolute ? to : to ? `${basePath}/${to}` : basePath
            const isReviewsItem = label === 'Reviews'

            return (
              <NavLink
                key={to || 'overview'}
                to={targetPath}
                end={end}
                className={linkClass}
                onClick={onNavigate}
              >
                <div className="flex items-center gap-3">
                  <Icon className="w-4 h-4 stroke-[2]" />
                  <span>{label}</span>
                </div>

                {isReviewsItem && pendingReviewsCount > 0 && (
                  <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800">
                    {pendingReviewsCount}
                  </span>
                )}
              </NavLink>
            )
          })}
        </nav>
      </div>

      {/* User Profile Widget at Bottom */}
      {user && (
        <div className="pt-3 border-t border-slate-100 flex items-center justify-between gap-2 px-1">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="w-9 h-9 rounded-full bg-slate-900 text-white text-xs font-bold flex items-center justify-center shrink-0">
              {initials}
            </div>
            <div className="min-w-0">
              <p className="text-xs font-bold text-slate-900 truncate leading-tight">
                {user.name || 'User'}
              </p>
              <p className="text-[11px] text-slate-500 truncate leading-tight mt-0.5">
                {user.email}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => logout()}
            className="w-8 h-8 rounded-lg hover:bg-red-50 text-slate-400 hover:text-red-600 flex items-center justify-center transition-colors shrink-0 cursor-pointer"
            title="Log out"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      )}
    </div>
  )
}

export function Sidebar() {
  return (
    <aside className="hidden w-64 shrink-0 border-r border-slate-200/90 bg-white md:flex md:flex-col h-screen sticky top-0 p-4">
      <SidebarNav className="flex-1" />
    </aside>
  )
}
