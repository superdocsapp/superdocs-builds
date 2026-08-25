import { useState, useRef, useEffect } from 'react'
import { Maximize2, Minimize2, Check } from 'lucide-react'
import type { FormattingItem } from '@/core/api/screenplayApi'
import type { ScreenplayScene, ScreenplayViewMode } from './types'
import { cn } from '@/lib/utils'

interface ScreenplayCenterViewProps {
  items: FormattingItem[]
  scenes: ScreenplayScene[]
  activeSceneNumber: number
  totalPages: number
  totalWords: number
  selectedItemIndex?: number
  selectedCharacterName?: string
  onSelectItem?: (item: FormattingItem) => void
  rawSourceText?: string
}

export function ScreenplayCenterView({
  items,
  scenes,
  activeSceneNumber,
  totalPages,
  totalWords,
  selectedItemIndex,
  selectedCharacterName,
  onSelectItem,
  rawSourceText,
}: ScreenplayCenterViewProps) {
  const [viewMode, setViewMode] = useState<ScreenplayViewMode>('formatted')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const elementRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const containerRef = useRef<HTMLDivElement>(null)

  // Scroll to active scene when selected
  useEffect(() => {
    const scene = scenes.find((s) => s.sceneNumber === activeSceneNumber)
    if (scene && scene.elementIndex !== undefined) {
      const el = elementRefs.current.get(scene.elementIndex)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  }, [activeSceneNumber, scenes])

  // Scroll to selected element if specified
  useEffect(() => {
    if (selectedItemIndex !== undefined) {
      const el = elementRefs.current.get(selectedItemIndex)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }
  }, [selectedItemIndex])

  const totalScenes = scenes.length > 0 ? scenes.length : 1
  const activeSceneObj = scenes.find((s) => s.sceneNumber === activeSceneNumber) || scenes[0]
  const currentSceneDisplay = activeSceneObj ? activeSceneObj.sceneNumber : 1
  const currentPageDisplay = activeSceneObj ? activeSceneObj.page : 1

  return (
    <div
      ref={containerRef}
      className={cn(
        'bg-white border border-slate-200/90 rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.02)] flex flex-col overflow-hidden transition-all duration-200',
        isFullscreen ? 'fixed inset-4 z-50 shadow-2xl rounded-2xl' : 'h-full min-h-[480px] lg:min-h-0 flex-1'
      )}
    >
      {/* 1. Header Toolbar */}
      <div className="px-4 py-2.5 border-b border-slate-200/80 bg-slate-50/50 flex items-center justify-between gap-3 shrink-0">
        {/* Left: Scene & Page Indicator */}
        <div className="flex items-center gap-2 text-xs font-semibold text-slate-700">
          <span>Scene {currentSceneDisplay}</span>
          <span className="text-slate-300">•</span>
          <span>Page {currentPageDisplay} of {totalPages}</span>
        </div>

        {/* Right: View Mode Toggle & Fullscreen */}
        <div className="flex items-center gap-2">
          <div className="flex items-center bg-slate-200/60 p-0.5 rounded-lg text-xs">
            <button
              type="button"
              onClick={() => setViewMode('formatted')}
              className={cn(
                'px-2.5 py-1 rounded-md font-semibold transition-all cursor-pointer',
                viewMode === 'formatted'
                  ? 'bg-white text-slate-900 shadow-xs'
                  : 'text-slate-600 hover:text-slate-900'
              )}
            >
              Formatted View
            </button>
            <button
              type="button"
              onClick={() => setViewMode('source')}
              className={cn(
                'px-2.5 py-1 rounded-md font-semibold transition-all cursor-pointer',
                viewMode === 'source'
                  ? 'bg-white text-slate-900 shadow-xs'
                  : 'text-slate-600 hover:text-slate-900'
              )}
            >
              Source View
            </button>
          </div>

          <button
            type="button"
            onClick={() => setIsFullscreen((prev) => !prev)}
            className="p-1.5 rounded-lg text-slate-500 hover:text-slate-900 hover:bg-slate-200/60 transition-colors cursor-pointer"
            title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen View'}
          >
            {isFullscreen ? (
              <Minimize2 className="w-4 h-4" />
            ) : (
              <Maximize2 className="w-4 h-4" />
            )}
          </button>
        </div>
      </div>

      {/* 2. Screenplay Document Viewer */}
      <div className="flex-1 min-h-0 bg-slate-100/70 p-4 sm:p-6 overflow-y-auto flex justify-center items-start">
        {viewMode === 'source' ? (
          /* Source View: Monospace unformatted text */
          <div className="w-full max-w-3xl bg-white border border-slate-200/80 rounded-lg shadow-sm p-6 sm:p-10 font-mono text-xs text-slate-800 leading-relaxed whitespace-pre-wrap selection:bg-blue-100 min-h-full h-fit mb-6">
            {rawSourceText ||
              items.map((it) => it.original_text || it.formatted_text).join('\n\n') ||
              'No source content available.'}
          </div>
        ) : (
          /* Formatted Screenplay Paper View */
          <div className="w-full max-w-3xl bg-white border border-slate-200/80 rounded-lg shadow-sm p-6 sm:p-12 font-mono text-[13px] text-slate-900 leading-relaxed selection:bg-blue-100 min-h-full h-fit mb-6">
            {items.length === 0 ? (
              <div className="text-center py-20 text-slate-400">
                <p>No screenplay elements to display.</p>
              </div>
            ) : (
              items.map((item) => {
                const isSelected = selectedItemIndex === item.element_index
                const isCharacterHighlighted =
                  selectedCharacterName &&
                  (item.character_name?.toLowerCase() === selectedCharacterName.toLowerCase() ||
                    (item.element_type === 'character' &&
                      item.formatted_text.toLowerCase().includes(selectedCharacterName.toLowerCase())))

                const displayText = item.formatted_text || item.original_text || ''

                return (
                  <div
                    key={item.id || item.element_index}
                    ref={(el) => {
                      if (el) elementRefs.current.set(item.element_index, el)
                    }}
                    onClick={() => onSelectItem?.(item)}
                    className={cn(
                      'transition-all duration-150 cursor-pointer rounded px-1.5 py-0.5 group relative',
                      isSelected && 'bg-blue-50/90 ring-1 ring-blue-300',
                      isCharacterHighlighted && !isSelected && 'bg-amber-50/60 ring-1 ring-amber-200',
                      !isSelected && !isCharacterHighlighted && 'hover:bg-slate-50'
                    )}
                  >
                    {/* Title */}
                    {item.element_type === 'title' && (
                      <div className="text-center font-bold uppercase tracking-wider text-slate-950 mt-2 mb-1">
                        {displayText}
                      </div>
                    )}

                    {/* Author */}
                    {['author', 'author_credit', 'credit'].includes(item.element_type) && (
                      <div className="text-center text-slate-700 mb-6 font-normal">
                        {displayText}
                      </div>
                    )}

                    {/* Scene Heading */}
                    {item.element_type === 'scene_heading' && (
                      <div className="flex items-center justify-between font-bold uppercase tracking-wide text-slate-950 mt-6 mb-2.5 pt-2 border-t border-slate-100 first:mt-0 first:pt-0 first:border-0">
                        <span className="text-slate-400 font-normal mr-2">
                          {item.scene_number || ''}
                        </span>
                        <span className="flex-1 font-bold">{displayText}</span>
                        <span className="text-slate-400 font-normal ml-2">
                          {item.scene_number || ''}
                        </span>
                      </div>
                    )}

                    {/* Action Block */}
                    {item.element_type === 'action' && (
                      <p className="my-2.5 text-slate-800 leading-relaxed font-normal">
                        {displayText}
                      </p>
                    )}

                    {/* Character Name */}
                    {item.element_type === 'character' && (
                      <div className="text-center mt-4 mb-0.5 uppercase font-bold tracking-wider text-slate-950 max-w-[65%] mx-auto">
                        {displayText}
                      </div>
                    )}

                    {/* Parenthetical */}
                    {item.element_type === 'parenthetical' && (
                      <div className="text-center text-slate-600 italic mb-0.5 max-w-[50%] mx-auto">
                        {displayText.startsWith('(') ? displayText : `(${displayText})`}
                      </div>
                    )}

                    {/* Dialogue */}
                    {item.element_type === 'dialogue' && (
                      <div className="text-left text-slate-900 mb-3 max-w-[65%] mx-auto leading-relaxed">
                        {displayText}
                      </div>
                    )}

                    {/* Transition */}
                    {item.element_type === 'transition' && (
                      <div className="text-right uppercase font-semibold text-slate-700 my-4">
                        {displayText}
                      </div>
                    )}

                    {/* End */}
                    {item.element_type === 'end' && (
                      <div className="text-center uppercase font-bold text-slate-950 my-6">
                        {displayText}
                      </div>
                    )}

                    {/* Generic fallback if unclassified */}
                    {![
                      'title',
                      'author',
                      'author_credit',
                      'credit',
                      'scene_heading',
                      'action',
                      'character',
                      'parenthetical',
                      'dialogue',
                      'transition',
                      'end',
                    ].includes(item.element_type) && (
                      <p className="my-2 text-slate-800">{displayText}</p>
                    )}
                  </div>
                )
              })
            )}
          </div>
        )}
      </div>

      {/* 3. Bottom Status Bar */}
      <div className="px-5 py-2.5 border-t border-slate-200/80 bg-slate-50/50 flex items-center justify-between text-xs text-slate-500 font-medium shrink-0">
        <div className="flex items-center gap-1.5 text-slate-600">
          <Check className="w-3.5 h-3.5 text-emerald-600 stroke-[2.5]" />
          <span>Last saved just now</span>
        </div>

        <div>
          <span>{totalPages} {totalPages === 1 ? 'page' : 'pages'}</span>
          <span className="mx-2 text-slate-300">•</span>
          <span>{totalScenes} {totalScenes === 1 ? 'scene' : 'scenes'}</span>
          <span className="mx-2 text-slate-300">•</span>
          <span>{totalWords.toLocaleString()} words</span>
        </div>
      </div>
    </div>
  )
}
