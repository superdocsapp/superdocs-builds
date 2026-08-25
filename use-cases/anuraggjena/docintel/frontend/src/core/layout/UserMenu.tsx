import { LogOut } from 'lucide-react'

import { useAuth } from '@/core/auth'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/shared/components/ui/dropdown-menu'

export function UserMenu() {
  const { user, logout } = useAuth()

  if (!user) {
    return null
  }

  // Get user initials (e.g., 'Anurag Jena' -> 'AJ' or email initial)
  const initials = user.name
    ? user.name
        .split(' ')
        .map((n) => n[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : (user.email?.[0] || 'U').toUpperCase()

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="w-10 h-10 rounded-full bg-slate-900 hover:bg-slate-800 text-white text-xs font-bold tracking-wider flex items-center justify-center shadow-sm transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-slate-900/25 cursor-pointer"
          aria-label="User profile menu"
        >
          {initials}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56 p-1.5 bg-white border border-slate-200 shadow-lg rounded-xl">
        <div className="px-2.5 py-2">
          <p className="text-sm font-semibold text-slate-900 leading-none truncate">
            {user.name || 'User'}
          </p>
          <p className="text-xs text-slate-500 mt-1 truncate">
            {user.email}
          </p>
        </div>
        <DropdownMenuSeparator className="my-1 bg-slate-100" />
        <DropdownMenuItem
          onClick={() => logout()}
          className="flex items-center gap-2 px-2.5 py-2 text-xs font-semibold text-red-600 hover:bg-red-50 focus:bg-red-50 focus:text-red-600 rounded-lg cursor-pointer transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" />
          <span>Log out</span>
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

