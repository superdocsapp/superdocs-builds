import type { ScreenplayCharacter } from './types'
import { Users } from 'lucide-react'
import { cn } from '@/lib/utils'

interface ScreenplayCharactersCardProps {
  characters: ScreenplayCharacter[]
  selectedCharacterName?: string
  onSelectCharacter?: (character: ScreenplayCharacter) => void
  onViewAllCharacters?: () => void
}

export function ScreenplayCharactersCard({
  characters,
  selectedCharacterName,
  onSelectCharacter,
  onViewAllCharacters,
}: ScreenplayCharactersCardProps) {
  return (
    <div className="bg-white border border-slate-200/90 rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col overflow-hidden shrink-0">
      {/* Header */}
      <div className="p-3.5 pb-2.5 border-b border-slate-100 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-bold text-slate-900 tracking-tight">Characters</h2>
          <span className="px-1.5 py-0.5 rounded text-[11px] font-semibold bg-slate-100 text-slate-600">
            {characters.length}
          </span>
        </div>

        {onViewAllCharacters && (
          <button
            type="button"
            onClick={onViewAllCharacters}
            className="text-xs font-semibold text-blue-600 hover:text-blue-700 transition-colors cursor-pointer"
          >
            All ({characters.length})
          </button>
        )}
      </div>

      {/* Characters List */}
      <div className="p-2 space-y-1 max-h-[220px] overflow-y-auto">
        {characters.length === 0 ? (
          <div className="p-4 text-center text-slate-400 text-xs">
            <Users className="w-5 h-5 mx-auto mb-1 text-slate-300" />
            <p>No characters identified</p>
          </div>
        ) : (
          characters.map((char) => {
            const isSelected = selectedCharacterName?.toLowerCase() === char.name.toLowerCase()

            return (
              <button
                key={char.name}
                type="button"
                onClick={() => onSelectCharacter?.(char)}
                className={cn(
                  'w-full flex items-center justify-between p-2 rounded-lg transition-colors text-left cursor-pointer',
                  isSelected
                    ? 'bg-blue-50/80 border border-blue-200 text-blue-900'
                    : 'hover:bg-slate-50 border border-transparent text-slate-800'
                )}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  {/* Initial Avatar */}
                  <div
                    className={cn(
                      'w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 border',
                      char.bgClass,
                      char.colorClass,
                      char.borderClass
                    )}
                  >
                    {char.initials}
                  </div>

                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-slate-900 truncate">
                      {char.name}
                    </p>
                    <p className="text-[10px] text-slate-400">
                      {char.dialogueCount} {char.dialogueCount === 1 ? 'line' : 'lines'}
                    </p>
                  </div>
                </div>
              </button>
            )
          })
        )}
      </div>
    </div>
  )
}
