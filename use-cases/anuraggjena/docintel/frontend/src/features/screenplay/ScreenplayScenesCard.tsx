import { useState, useMemo } from 'react'
import { Search, Clapperboard } from 'lucide-react'
import type { ScreenplayScene } from './types'
import { cn } from '@/lib/utils'

interface ScreenplayScenesCardProps {
  scenes: ScreenplayScene[]
  selectedSceneNumber?: number
  onSelectScene: (scene: ScreenplayScene) => void
}

export function ScreenplayScenesCard({
  scenes,
  selectedSceneNumber,
  onSelectScene,
}: ScreenplayScenesCardProps) {
  const [search, setSearch] = useState('')

  const filteredScenes = useMemo(() => {
    if (!search.trim()) return scenes
    const query = search.trim().toLowerCase()
    return scenes.filter(
      (s) =>
        s.heading.toLowerCase().includes(query) ||
        `scene ${s.sceneNumber}`.includes(query) ||
        `page ${s.page}`.includes(query)
    )
  }, [scenes, search])

  return (
    <div className="bg-white border border-slate-200/90 rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col overflow-hidden min-h-0 flex-1">
      {/* Header */}
      <div className="p-3.5 pb-2 border-b border-slate-100 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900 tracking-tight">Scenes</h2>
          <span className="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-slate-100 text-slate-600">
            {scenes.length}
          </span>
        </div>
      </div>

      {/* Search Input */}
      <div className="p-2.5 border-b border-slate-100 bg-slate-50/40 shrink-0">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400 pointer-events-none" />
          <input
            type="text"
            placeholder="Search scenes…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full h-8 pl-8 pr-2.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 transition-colors"
          />
        </div>
      </div>

      {/* Scenes List */}
      <div className="flex-1 min-h-0 max-h-[300px] lg:max-h-none overflow-y-auto divide-y divide-slate-100/80 p-1">
        {filteredScenes.length === 0 ? (
          <div className="p-6 text-center text-slate-400 text-xs">
            <Clapperboard className="w-5 h-5 mx-auto mb-1 text-slate-300" />
            <p>No scenes matching &ldquo;{search}&rdquo;</p>
          </div>
        ) : (
          filteredScenes.map((scene) => {
            const isSelected = selectedSceneNumber === scene.sceneNumber

            return (
              <button
                key={scene.sceneNumber}
                type="button"
                onClick={() => onSelectScene(scene)}
                className={cn(
                  'w-full text-left p-2.5 rounded-lg flex items-start gap-2.5 transition-all duration-150 cursor-pointer',
                  isSelected
                    ? 'bg-blue-50/80 border border-blue-200/80 text-blue-900 shadow-xs'
                    : 'hover:bg-slate-50 text-slate-700 border border-transparent'
                )}
              >
                {/* Scene Number Badge */}
                <div
                  className={cn(
                    'w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold shrink-0 mt-0.5',
                    isSelected
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-100 text-slate-600'
                  )}
                >
                  {scene.sceneNumber}
                </div>

                {/* Scene Heading and Page */}
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      'text-xs font-semibold uppercase leading-snug line-clamp-2',
                      isSelected ? 'text-blue-950 font-bold' : 'text-slate-900'
                    )}
                  >
                    {scene.heading}
                  </p>
                  <p className="text-[10px] text-slate-400 mt-0.5">
                    Page {scene.page}
                  </p>
                </div>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
