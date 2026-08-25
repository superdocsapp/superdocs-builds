import { Clapperboard, FileText, AlignLeft, Sparkles } from 'lucide-react'
import type { ScreenplayAnalysisMetrics } from './types'

interface ScreenplayAnalysisCardProps {
  metrics: ScreenplayAnalysisMetrics
}

export function ScreenplayAnalysisCard({ metrics }: ScreenplayAnalysisCardProps) {
  return (
    <div className="bg-white border border-slate-200/90 rounded-xl shadow-[0_1px_2px_rgba(0,0,0,0.02)] p-3.5 space-y-2.5 shrink-0">
      <h2 className="text-sm font-bold text-slate-900 tracking-tight">Formatting Analysis</h2>

      <div className="grid grid-cols-2 gap-2">
        {/* Scenes Metric */}
        <div className="p-2.5 rounded-lg bg-slate-50/80 border border-slate-100 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-[11px] font-semibold text-slate-600">Scenes</span>
            <Clapperboard className="w-3.5 h-3.5 text-purple-600" />
          </div>
          <p className="text-base font-bold text-slate-900 mt-0.5">
            {metrics.scenesCount}
          </p>
        </div>

        {/* Pages Metric */}
        <div className="p-2.5 rounded-lg bg-slate-50/80 border border-slate-100 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-[11px] font-semibold text-slate-600">Pages</span>
            <FileText className="w-3.5 h-3.5 text-emerald-600" />
          </div>
          <p className="text-base font-bold text-slate-900 mt-0.5">
            {metrics.pagesCount}
          </p>
        </div>

        {/* Words Metric */}
        <div className="p-2.5 rounded-lg bg-slate-50/80 border border-slate-100 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-[11px] font-semibold text-slate-600">Words</span>
            <AlignLeft className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <p className="text-base font-bold text-slate-900 mt-0.5">
            {metrics.wordsCount.toLocaleString()}
          </p>
        </div>

        {/* Formatting Score Metric */}
        <div className="p-2.5 rounded-lg bg-slate-50/80 border border-slate-100 flex flex-col justify-between">
          <div className="flex items-center justify-between text-slate-500">
            <span className="text-[11px] font-semibold text-slate-600">Score</span>
            <Sparkles className="w-3.5 h-3.5 text-amber-500" />
          </div>
          <p className="text-base font-bold text-slate-900 mt-0.5">
            {metrics.formattingScore}%
          </p>
        </div>
      </div>
    </div>
  )
}
