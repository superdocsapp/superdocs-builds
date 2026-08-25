import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  Check,
  CheckCheck,
  X,
  Copy,
  Clock,
  Search,
  MessageSquare,
  Lock,
  FileText,
  Columns,
} from 'lucide-react'

import type { RunClaim } from '@/core/api/workflowApi'
import { formatDate } from '@/shared/utils/formatDate'
import { cn } from '@/lib/utils'

export interface ParsedClaimChange {
  id: string
  changeId: string
  chunkId: string
  type: 'added' | 'removed' | 'modified'
  section: string
  page: string
  description: string
  aiExplanation: string | null
  oldHtml: string | null
  newHtml: string | null
  status: 'pending' | 'approved' | 'rejected'
  sourceStage?: string | null
  confidenceScore?: string | null
}

function formatLabel(str: string): string {
  return str
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
}

export function normalizeStatus(rawStatus?: string | null): 'pending' | 'approved' | 'rejected' {
  if (!rawStatus) return 'pending'
  const s = rawStatus.toLowerCase().trim()
  if (s === 'approved' || s === 'accepted') return 'approved'
  if (s === 'rejected' || s === 'declined') return 'rejected'
  return 'pending'
}

export function parseClaim(claim: RunClaim): ParsedClaimChange {
  let parsedJson: Record<string, any> | null = null
  if (claim.content && typeof claim.content === 'string') {
    const trimmed = claim.content.trim()
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      try {
        parsedJson = JSON.parse(trimmed)
      } catch {
        parsedJson = null
      }
    }
  }

  const status = normalizeStatus(claim.status)
  const sourceStage = claim.source_stage || null
  const confidenceScore = claim.confidence_score || (parsedJson?.confidence ? String(parsedJson.confidence) : null)

  if (parsedJson && typeof parsedJson === 'object') {
    const oldHtml: string | null =
      parsedJson.old_html ??
      parsedJson.old_content ??
      parsedJson.original_content ??
      claim.original_content ??
      null

    const newHtml: string | null =
      parsedJson.new_html ??
      parsedJson.new_content ??
      parsedJson.content ??
      parsedJson.content_preview ??
      (typeof claim.content === 'string' && !claim.content.startsWith('{') ? claim.content : null)

    const aiExplanation: string | null =
      parsedJson.ai_explanation ??
      parsedJson.analyst_reasoning ??
      parsedJson.reason ??
      parsedJson.explanation ??
      parsedJson.rationale ??
      null

    const changeId: string = String(
      parsedJson.superdocs_change_id ??
      parsedJson.memo_section_id ??
      parsedJson.change_id ??
      claim.id
    )

    const chunkId: string = parsedJson.chunk_id ? String(parsedJson.chunk_id) : ''

    // Section naming
    let section = 'Document Change'
    if (parsedJson.title) {
      section = parsedJson.title
    } else if (parsedJson.section) {
      section = parsedJson.section
    } else if (parsedJson.section_name) {
      section = parsedJson.section_name
    } else if (parsedJson.section_type) {
      section = formatLabel(parsedJson.section_type)
    } else if (parsedJson.field) {
      section = `Field: ${formatLabel(parsedJson.field)}`
    } else if (claim.claim_type) {
      section = formatLabel(claim.claim_type)
    }

    // Page / Section order naming
    let page = 'Section 1'
    if (parsedJson.page != null) {
      page = `Page ${parsedJson.page}`
    } else if (parsedJson.page_number != null) {
      page = `Page ${parsedJson.page_number}`
    } else if (parsedJson.section_order != null) {
      page = `Section ${parsedJson.section_order}`
    } else if (chunkId) {
      page = `Chunk ${chunkId}`
    } else if (claim.source_stage) {
      page = formatLabel(claim.source_stage)
    }

    // Change type calculation
    let type: 'added' | 'removed' | 'modified' = 'modified'
    if (parsedJson.type === 'added' || parsedJson.change_type === 'added') {
      type = 'added'
    } else if (parsedJson.type === 'removed' || parsedJson.change_type === 'removed') {
      type = 'removed'
    } else if (parsedJson.type === 'modified' || parsedJson.change_type === 'modified') {
      type = 'modified'
    } else if (!oldHtml && newHtml) {
      type = 'added'
    } else if (oldHtml && !newHtml) {
      type = 'removed'
    } else {
      type = 'modified'
    }

    // Description
    const rawPreview = newHtml || oldHtml || ''
    const cleanPreview = rawPreview.replace(/<[^>]+>/g, '').trim()
    const description =
      parsedJson.description ||
      parsedJson.summary ||
      parsedJson.title ||
      (aiExplanation ? aiExplanation.slice(0, 100) : null) ||
      (cleanPreview ? (cleanPreview.length > 100 ? `${cleanPreview.slice(0, 100)}…` : cleanPreview) : null) ||
      `${formatLabel(claim.claim_type || 'Proposed Change')}`

    return {
      id: claim.id,
      changeId,
      chunkId,
      type,
      section,
      page,
      description,
      aiExplanation,
      oldHtml,
      newHtml,
      status,
      sourceStage,
      confidenceScore,
    }
  }

  // Plain string content (non-JSON)
  const oldHtml = claim.original_content || null
  const newHtml = claim.content || null
  const type: 'added' | 'removed' | 'modified' = !oldHtml && newHtml ? 'added' : oldHtml && !newHtml ? 'removed' : 'modified'
  const cleanPreview = (newHtml || oldHtml || '').replace(/<[^>]+>/g, '').trim()
  const description = cleanPreview.length > 100 ? `${cleanPreview.slice(0, 100)}…` : cleanPreview || 'Proposed change'

  return {
    id: claim.id,
    changeId: claim.id,
    chunkId: '',
    type,
    section: claim.claim_type ? formatLabel(claim.claim_type) : 'Document Change',
    page: claim.source_stage ? formatLabel(claim.source_stage) : 'General',
    description,
    aiExplanation: null,
    oldHtml,
    newHtml,
    status,
    sourceStage,
    confidenceScore,
  }
}

export interface HumanApprovalModalProps {
  open: boolean
  onClose: () => void
  claims: RunClaim[]
  runId: string
  workspaceName?: string
  startedAt?: string
  error?: string | null
  onApprove: (claimId: string) => void
  onReject: (claimId: string) => void
  onApproveAll?: () => void
  isActing: boolean
  isApprovingAll?: boolean
}

export function HumanApprovalModal({
  open,
  onClose,
  claims,
  runId,
  workspaceName,
  startedAt,
  error,
  onApprove,
  onReject,
  onApproveAll,
  isActing,
  isApprovingAll = false,
}: HumanApprovalModalProps) {
  const [activeTab, setActiveTab] = useState<'changes' | 'notes'>('changes')
  const [searchQuery, setSearchQuery] = useState('')
  const [showOnlyChanges, setShowOnlyChanges] = useState(true)
  const [viewMode, setViewMode] = useState<'unified' | 'side-by-side'>('unified')
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null)
  const [copiedRunId, setCopiedRunId] = useState(false)
  const [notes, setNotes] = useState<string[]>([])
  const [noteInput, setNoteInput] = useState('')
  const [showNoteForm, setShowNoteForm] = useState(false)

  // Single authoritative parsed and deduplicated collection
  const parsedClaims = useMemo(() => {
    const raw = claims.map(parseClaim)
    const seen = new Set<string>()
    const deduplicated: ParsedClaimChange[] = []
    for (const c of raw) {
      const key = c.changeId || c.id
      if (!seen.has(key)) {
        seen.add(key)
        deduplicated.push(c)
      }
    }
    return deduplicated
  }, [claims])

  // Stats calculation directly from the authoritative collection
  const counts = useMemo(() => {
    let added = 0
    let removed = 0
    let modified = 0
    let pending = 0
    let approved = 0
    let rejected = 0

    for (const c of parsedClaims) {
      if (c.type === 'added') added++
      else if (c.type === 'removed') removed++
      else modified++

      if (c.status === 'approved') approved++
      else if (c.status === 'rejected') rejected++
      else pending++
    }

    return {
      added,
      removed,
      modified,
      pending,
      approved,
      rejected,
      total: parsedClaims.length,
    }
  }, [parsedClaims])

  // Filtered claims strictly using the same collection
  const filteredClaims = useMemo(() => {
    return parsedClaims.filter((claim) => {
      if (showOnlyChanges && claim.status !== 'pending') return false
      if (!searchQuery.trim()) return true
      const q = searchQuery.toLowerCase()
      return (
        claim.description.toLowerCase().includes(q) ||
        (claim.aiExplanation && claim.aiExplanation.toLowerCase().includes(q)) ||
        claim.section.toLowerCase().includes(q)
      )
    })
  }, [parsedClaims, showOnlyChanges, searchQuery])

  // Active selected claim strictly derived from filtered or parsed list
  const activeClaim = useMemo(() => {
    if (selectedClaimId) {
      const found = filteredClaims.find((c) => c.id === selectedClaimId) || parsedClaims.find((c) => c.id === selectedClaimId)
      if (found) return found
    }
    return filteredClaims[0] ?? (showOnlyChanges ? null : parsedClaims[0]) ?? null
  }, [selectedClaimId, filteredClaims, parsedClaims, showOnlyChanges])

  if (!open) return null

  const handleCopyRunId = () => {
    navigator.clipboard.writeText(runId)
    setCopiedRunId(true)
    setTimeout(() => setCopiedRunId(false), 2000)
  }

  const handleAddNote = (e: React.FormEvent) => {
    e.preventDefault()
    if (noteInput.trim()) {
      setNotes((prev) => [...prev, noteInput.trim()])
      setNoteInput('')
      setShowNoteForm(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-3 sm:p-4 animate-in fade-in duration-200">
      <div className="bg-white border border-slate-200/90 rounded-2xl shadow-2xl w-full max-w-5xl max-h-[92vh] flex flex-col overflow-hidden">
        {/* 1. Header */}
        <div className="flex items-start justify-between px-6 pt-5 pb-4 border-b border-slate-100">
          <div className="flex items-start gap-3.5">
            <div className="w-10 h-10 rounded-xl bg-amber-50 text-amber-600 border border-amber-200/60 flex items-center justify-center shrink-0 mt-0.5">
              <AlertTriangle className="w-5 h-5 stroke-[2.25]" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base sm:text-lg font-bold text-slate-900 tracking-tight">
                  Human Review Required
                </h2>
                {counts.pending > 0 ? (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-200/80">
                    {counts.pending} pending
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-800 border border-emerald-200/80">
                    <Check className="w-3 h-3" /> All resolved
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Review and approve the changes before the workflow can continue.
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {onApproveAll && (
              <button
                type="button"
                disabled={counts.pending === 0 || isActing || isApprovingAll}
                onClick={onApproveAll}
                className={cn(
                  'inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-xl border transition-all cursor-pointer shadow-2xs',
                  counts.pending > 0
                    ? 'bg-emerald-600 hover:bg-emerald-700 text-white border-emerald-600 active:bg-emerald-800'
                    : 'bg-slate-100 text-slate-400 border-slate-200 cursor-not-allowed opacity-60'
                )}
                title={counts.pending === 0 ? 'No pending changes to approve' : 'Approve all pending changes'}
              >
                <CheckCheck className="w-3.5 h-3.5" />
                <span>{isApprovingAll ? 'Approving all…' : `Approve all (${counts.pending})`}</span>
              </button>
            )}

            <button
              type="button"
              onClick={onClose}
              className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {error && (
          <div className="px-6 py-2.5 bg-rose-50 border-b border-rose-200 flex items-center gap-2 text-xs text-rose-800">
            <AlertTriangle className="w-4 h-4 text-rose-600 shrink-0" />
            <span className="font-medium">{error}</span>
          </div>
        )}

        {/* 2. Metadata Summary Bar */}
        <div className="bg-slate-50/70 border-b border-slate-100 px-6 py-3 grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
              Workflow Run
            </span>
            <div className="flex items-center gap-1.5">
              <span className="font-mono font-medium text-slate-800 truncate max-w-[120px]">
                {runId.slice(0, 8)}…{runId.slice(-4)}
              </span>
              <button
                type="button"
                onClick={handleCopyRunId}
                title="Copy Run ID"
                className="text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                {copiedRunId ? <Check className="w-3 h-3 text-emerald-600" /> : <Copy className="w-3 h-3" />}
              </button>
            </div>
          </div>

          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
              {workspaceName ? 'Workspace' : 'Stage'}
            </span>
            <span className="font-semibold text-slate-800 truncate block">
              {workspaceName || 'Human Review'}
            </span>
          </div>

          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
              Requested at
            </span>
            <span className="text-slate-700">
              {startedAt ? formatDate(startedAt) : 'Just now'}
            </span>
          </div>

          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
              Decision Status
            </span>
            <span className="font-medium text-slate-700">
              {counts.approved} approved • {counts.rejected} rejected
            </span>
          </div>

          <div>
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400 block mb-0.5">
              Pending Changes
            </span>
            <div className="flex items-center gap-1 text-amber-700 font-medium">
              <Clock className="w-3 h-3" />
              <span>{counts.pending} awaiting decision</span>
            </div>
          </div>
        </div>

        {/* 3. Navigation Tabs */}
        <div className="flex items-center gap-6 px-6 border-b border-slate-200/80 bg-white">
          <button
            type="button"
            onClick={() => setActiveTab('changes')}
            className={cn(
              'py-2.5 text-xs font-bold border-b-2 transition-colors cursor-pointer',
              activeTab === 'changes'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            )}
          >
            Changes to Review ({parsedClaims.length})
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('notes')}
            className={cn(
              'py-2.5 text-xs font-bold border-b-2 transition-colors cursor-pointer',
              activeTab === 'notes'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-slate-500 hover:text-slate-800'
            )}
          >
            Review Notes ({notes.length})
          </button>
        </div>

        {/* 4. Main Body */}
        {activeTab === 'notes' ? (
          <div className="flex-1 overflow-y-auto p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider">
                Reviewer Notes
              </h3>
              <button
                type="button"
                onClick={() => setShowNoteForm((v) => !v)}
                className="text-xs font-semibold text-blue-600 hover:text-blue-700 cursor-pointer"
              >
                + Add Note
              </button>
            </div>

            {showNoteForm && (
              <form onSubmit={handleAddNote} className="space-y-2 bg-slate-50 p-4 rounded-xl border border-slate-200">
                <textarea
                  value={noteInput}
                  onChange={(e) => setNoteInput(e.target.value)}
                  placeholder="Type an audit or review note..."
                  rows={3}
                  className="w-full text-xs p-3 bg-white border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-600"
                />
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setShowNoteForm(false)}
                    className="px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-200 rounded-lg"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-3 py-1.5 text-xs font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                  >
                    Save Note
                  </button>
                </div>
              </form>
            )}

            {notes.length === 0 ? (
              <div className="text-center py-12 text-slate-400 text-xs">
                <MessageSquare className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                <p>No review notes added yet.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {notes.map((n, i) => (
                  <div key={i} className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-xs text-slate-700">
                    {n}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-12 divide-y md:divide-y-0 md:divide-x divide-slate-200">
            {/* Left Column: Change Summary & List (5 cols) */}
            <div className="md:col-span-5 flex flex-col min-h-0 bg-slate-50/40 p-4 sm:p-5 space-y-4 overflow-y-auto">
              {/* Summary Cards */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-bold text-slate-700 uppercase tracking-wider block">
                    Review Summary ({counts.total})
                  </span>
                  <div className="flex items-center gap-1.5 text-[10px] font-medium text-slate-500">
                    <span className="text-emerald-700 font-semibold">{counts.approved} approved</span>
                    <span>•</span>
                    <span className="text-rose-700 font-semibold">{counts.rejected} rejected</span>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div className="bg-emerald-50 border border-emerald-200/70 rounded-xl p-2.5 text-center">
                    <div className="text-emerald-700 text-xs font-bold flex items-center justify-center gap-1">
                      <span>⊕</span>
                      <span>{counts.added}</span>
                    </div>
                    <span className="text-[10px] font-semibold text-emerald-600 uppercase">Added</span>
                  </div>

                  <div className="bg-rose-50 border border-rose-200/70 rounded-xl p-2.5 text-center">
                    <div className="text-rose-700 text-xs font-bold flex items-center justify-center gap-1">
                      <span>⊖</span>
                      <span>{counts.removed}</span>
                    </div>
                    <span className="text-[10px] font-semibold text-rose-600 uppercase">Removed</span>
                  </div>

                  <div className="bg-amber-50 border border-amber-200/70 rounded-xl p-2.5 text-center">
                    <div className="text-amber-700 text-xs font-bold flex items-center justify-center gap-1">
                      <span>✎</span>
                      <span>{counts.modified}</span>
                    </div>
                    <span className="text-[10px] font-semibold text-amber-600 uppercase">Modified</span>
                  </div>
                </div>
              </div>

              {/* Filters */}
              <div className="space-y-2">
                <label className="flex items-center gap-2 text-xs font-medium text-slate-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={showOnlyChanges}
                    onChange={(e) => setShowOnlyChanges(e.target.checked)}
                    className="w-3.5 h-3.5 rounded border-slate-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                  />
                  <span>Show only pending changes ({counts.pending})</span>
                </label>

                <div className="relative">
                  <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
                  <input
                    type="text"
                    placeholder="Search changes..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full h-8 pl-8 pr-3 bg-white border border-slate-200 rounded-lg text-xs placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-600"
                  />
                </div>
              </div>

              {/* Claims List */}
              <div className="space-y-2 flex-1">
                {filteredClaims.length === 0 ? (
                  <p className="text-xs text-slate-400 text-center py-6">
                    {showOnlyChanges && counts.pending === 0
                      ? 'All changes in this run have been decided.'
                      : 'No matching changes found.'}
                  </p>
                ) : (
                  filteredClaims.map((claim) => {
                    const isSelected = activeClaim?.id === claim.id
                    return (
                      <div
                        key={claim.id}
                        onClick={() => setSelectedClaimId(claim.id)}
                        className={cn(
                          'p-3 rounded-xl border text-left cursor-pointer transition-all duration-150 space-y-1.5',
                          isSelected
                            ? 'bg-white border-blue-500 ring-2 ring-blue-500/10 shadow-xs'
                            : 'bg-white border-slate-200/90 hover:border-slate-300 hover:bg-slate-50/60'
                        )}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={cn(
                              'inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border uppercase',
                              claim.type === 'added'
                                ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                : claim.type === 'removed'
                                  ? 'bg-rose-50 text-rose-700 border-rose-200'
                                  : 'bg-amber-50 text-amber-700 border-amber-200'
                            )}
                          >
                            {claim.type === 'added' ? '+ Added' : claim.type === 'removed' ? '- Removed' : '✏ Modified'}
                          </span>
                          <span className="text-[10px] text-slate-400 font-medium">{claim.page}</span>
                        </div>
                        <p className="text-xs font-semibold text-slate-800 line-clamp-2 leading-snug">
                          {claim.description}
                        </p>
                        <div className="flex items-center justify-between text-[10px] text-slate-400">
                          <span className="truncate max-w-[150px]">{claim.section}</span>
                          <span
                            className={cn(
                              'inline-block px-1.5 py-0.2 rounded font-semibold uppercase',
                              claim.status === 'approved'
                                ? 'bg-emerald-100 text-emerald-800'
                                : claim.status === 'rejected'
                                  ? 'bg-rose-100 text-rose-800'
                                  : 'bg-amber-100 text-amber-800'
                            )}
                          >
                            {claim.status}
                          </span>
                        </div>
                      </div>
                    )
                  })
                )}
              </div>
            </div>

            {/* Right Column: Document Change Preview (7 cols) */}
            <div className="md:col-span-7 flex flex-col min-h-0 bg-white p-5 sm:p-6 space-y-4 overflow-y-auto">
              {/* Preview Header */}
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-slate-100">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
                      Change Preview
                    </h3>
                    {activeClaim && (
                      <span
                        className={cn(
                          'inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-bold uppercase',
                          activeClaim.status === 'approved'
                            ? 'bg-emerald-100 text-emerald-800'
                            : activeClaim.status === 'rejected'
                              ? 'bg-rose-100 text-rose-800'
                              : 'bg-amber-100 text-amber-800'
                        )}
                      >
                        {activeClaim.status}
                      </span>
                    )}
                  </div>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    {activeClaim ? `${activeClaim.section} • ${activeClaim.page}` : 'Classification Document'}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <div className="hidden sm:flex items-center gap-2 text-[11px] font-medium mr-2">
                    <span className="inline-flex items-center gap-1 text-emerald-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> Added
                    </span>
                    <span className="inline-flex items-center gap-1 text-rose-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span> Removed
                    </span>
                    <span className="inline-flex items-center gap-1 text-amber-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-500"></span> Modified
                    </span>
                  </div>

                  <button
                    type="button"
                    onClick={() => setViewMode((m) => (m === 'unified' ? 'side-by-side' : 'unified'))}
                    className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-slate-600 bg-slate-100 hover:bg-slate-200 rounded-lg transition-colors cursor-pointer"
                  >
                    <Columns className="w-3 h-3" />
                    <span>{viewMode === 'unified' ? 'Side-by-side' : 'Unified view'}</span>
                  </button>
                </div>
              </div>

              {/* Preview Body */}
              {activeClaim ? (
                <div className="space-y-4">
                  {/* AI Explanation / Reason for Change */}
                  {activeClaim.aiExplanation && (
                    <div className="p-3.5 bg-blue-50/60 border border-blue-200/70 rounded-xl space-y-1">
                      <span className="text-[10px] font-bold text-blue-800 uppercase tracking-wider">
                        Why this change is proposed
                      </span>
                      <p className="text-xs text-blue-950 leading-relaxed font-medium">
                        {activeClaim.aiExplanation}
                      </p>
                    </div>
                  )}

                  {/* Document Text / HTML comparison */}
                  {viewMode === 'side-by-side' ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      {/* Original */}
                      <div className="p-3.5 bg-rose-50/30 border border-rose-200/60 rounded-xl space-y-1.5">
                        <span className="text-[10px] font-bold text-rose-800 uppercase tracking-wider">
                          Original Content
                        </span>
                        <div
                          className="text-xs text-slate-700 leading-relaxed font-serif whitespace-pre-wrap max-h-60 overflow-y-auto"
                          dangerouslySetInnerHTML={{
                            __html:
                              activeClaim.oldHtml ||
                              '<span class="text-slate-400 italic font-sans">(None — newly added)</span>',
                          }}
                        />
                      </div>

                      {/* Proposed */}
                      <div className="p-3.5 bg-emerald-50/30 border border-emerald-200/60 rounded-xl space-y-1.5">
                        <span className="text-[10px] font-bold text-emerald-800 uppercase tracking-wider">
                          Proposed Content
                        </span>
                        <div
                          className="text-xs text-slate-900 leading-relaxed font-serif whitespace-pre-wrap max-h-60 overflow-y-auto"
                          dangerouslySetInnerHTML={{
                            __html:
                              activeClaim.newHtml ||
                              '<span class="text-slate-400 italic font-sans">(None — removed)</span>',
                          }}
                        />
                      </div>
                    </div>
                  ) : (
                    /* Unified View */
                    <div className="p-4 bg-slate-50/50 border border-slate-200/80 rounded-xl space-y-3 font-serif">
                      {activeClaim.oldHtml && (
                        <div className="space-y-1">
                          <span className="text-[10px] font-sans font-bold text-rose-700 uppercase tracking-wider">
                            Original
                          </span>
                          <div
                            className="text-xs text-rose-900 bg-rose-50/70 border border-rose-200/50 rounded-lg p-3 leading-relaxed line-through whitespace-pre-wrap"
                            dangerouslySetInnerHTML={{ __html: activeClaim.oldHtml }}
                          />
                        </div>
                      )}

                      {activeClaim.newHtml ? (
                        <div className="space-y-1">
                          <span className="text-[10px] font-sans font-bold text-emerald-700 uppercase tracking-wider">
                            Proposed
                          </span>
                          <div
                            className="text-xs text-emerald-950 bg-emerald-50/70 border border-emerald-200/50 rounded-lg p-3 leading-relaxed whitespace-pre-wrap font-medium"
                            dangerouslySetInnerHTML={{ __html: activeClaim.newHtml }}
                          />
                        </div>
                      ) : (
                        <div className="text-xs text-slate-400 italic font-sans">
                          (None — removed)
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <div className="py-12 text-center text-slate-400 text-xs">
                  <FileText className="w-8 h-8 mx-auto mb-2 text-slate-300" />
                  <p>Select a change on the left to preview.</p>
                </div>
              )}
            </div>
          </div>
        )}

        {/* 5. Footer */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-6 py-4 border-t border-slate-200/90 bg-slate-50/60">
          <button
            type="button"
            onClick={() => {
              setActiveTab('notes')
              setShowNoteForm(true)
            }}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:text-slate-900 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-colors cursor-pointer"
          >
            <MessageSquare className="w-3.5 h-3.5" />
            <span>Add Review Note</span>
          </button>

          <div className="flex items-center gap-1.5 text-[11px] text-slate-400 font-medium">
            <Lock className="w-3 h-3 text-slate-400" />
            <span>Your decision will be recorded in the audit trail.</span>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
            {activeClaim?.status === 'approved' ? (
              <span className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-emerald-800 bg-emerald-100 border border-emerald-200 rounded-xl">
                <Check className="w-3.5 h-3.5" />
                <span>Decision: Approved</span>
              </span>
            ) : activeClaim?.status === 'rejected' ? (
              <span className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold text-rose-800 bg-rose-100 border border-rose-200 rounded-xl">
                <X className="w-3.5 h-3.5" />
                <span>Decision: Rejected</span>
              </span>
            ) : (
              <>
                <button
                  type="button"
                  disabled={isActing || !activeClaim || activeClaim.status !== 'pending'}
                  onClick={() => {
                    if (activeClaim) onReject(activeClaim.id)
                  }}
                  className="px-4 py-2 text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 rounded-xl transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Reject
                </button>
                <button
                  type="button"
                  disabled={isActing || !activeClaim || activeClaim.status !== 'pending'}
                  onClick={() => {
                    if (activeClaim) onApprove(activeClaim.id)
                  }}
                  className="inline-flex items-center gap-1.5 px-5 py-2 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Check className="w-3.5 h-3.5" />
                  <span>{isActing ? 'Updating…' : 'Approve & Continue'}</span>
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
