import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, Plus } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import { workspaceApi } from '@/core/api/client'
import { cn } from '@/lib/utils'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'

export function WorkspaceSelector({ className }: { className?: string }) {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const navigate = useNavigate()

  const { data: workspaces, isLoading } = useQuery({
    queryKey: ['workspaces'],
    queryFn: () => workspaceApi.list(),
  })

  const currentWorkspace = workspaces?.find((workspace) => workspace.id === workspaceId)
  const label = isLoading
    ? 'Loading…'
    : currentWorkspace?.name ?? 'Select workspace'

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          disabled={isLoading}
          className={cn(
            'w-full flex items-center justify-between px-3 py-2 bg-white border border-slate-200 rounded-lg text-xs font-semibold text-slate-800 shadow-[0_1px_2px_rgba(0,0,0,0.03)] hover:border-slate-300 hover:bg-slate-50/50 transition-colors focus:outline-none focus:ring-1 focus:ring-blue-600 cursor-pointer',
            className
          )}
        >
          <span className="truncate pr-2">{label}</span>
          <ChevronDown className="w-3.5 h-3.5 text-slate-400 shrink-0" />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[230px] p-1.5 bg-white border border-slate-200 rounded-xl shadow-lg">
        <DropdownMenuLabel className="px-2.5 py-1.5 text-xs font-semibold text-slate-500 uppercase tracking-wider">
          Workspaces
        </DropdownMenuLabel>
        <DropdownMenuSeparator className="my-1 bg-slate-100" />
        <div className="max-h-60 overflow-y-auto space-y-0.5">
          {workspaces?.map((workspace) => (
            <DropdownMenuItem
              key={workspace.id}
              onClick={() => navigate(`/workspace/${workspace.id}`)}
              className={cn(
                'flex items-center justify-between px-2.5 py-2 text-xs font-medium rounded-lg cursor-pointer transition-colors',
                workspace.id === workspaceId
                  ? 'bg-blue-50 text-blue-700 font-semibold'
                  : 'text-slate-700 hover:bg-slate-50'
              )}
            >
              <span className="truncate">{workspace.name}</span>
              {workspace.id === workspaceId && (
                <Check className="w-3.5 h-3.5 text-blue-600 shrink-0" />
              )}
            </DropdownMenuItem>
          ))}
        </div>
        <DropdownMenuSeparator className="my-1 bg-slate-100" />
        <DropdownMenuItem asChild className="cursor-pointer">
          <Link
            to="/workspaces"
            className="flex items-center gap-2 px-2.5 py-2 text-xs font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-50 rounded-lg transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>All workspaces</span>
          </Link>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

