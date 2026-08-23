import { useCallback, useEffect, useRef, useState } from 'react'
import {
  initZoomSdk,
  getMeetingContext,
  getMeetingJoinUrl,
  getUserContext,
  getMeetingUUID,
  isSupported,
  startCollaborate,
  endCollaborate,
  collaborateSupported,
} from './zoom/sdk.js'
import { useMeetingSession } from './hooks/useMeetingSession.js'

/* ------------------------------------------------------------------ */
/*  Presentation helpers — internal state → human language            */
/* ------------------------------------------------------------------ */

const TEMPLATE_LABELS = {
  statement_of_work: 'Statement of Work',
  meeting_minutes: 'Meeting Minutes',
  proposal: 'Proposal',
  advice_note: 'Advice Note',
  requirements_list: 'Requirements',
}

function templateLabelOf(session) {
  const active = session.documents?.find((d) => d.document_id === session.activeDocumentId)
  const key = active?.template_key || session.active_template_key
  return TEMPLATE_LABELS[key] || 'Document'
}

// One place that turns session state into what a meeting participant sees:
// the capture state and the draft state, combined into a single honest
// label. Never exposes provider names, job_status strings, or UUIDs.
//
// The capture states now come from the helper control channel (helper_status),
// which only advances on the helper's ACK — never claimed optimistically.
// Document-pipeline states (processing/review/error) still surface so a
// drafting run is visible. When no helper is connected, we say so plainly
// rather than pretending audio is active.
function sessionState(session) {
  const h = session.helper_status
  if (h === 'listening') return { key: 'listening', label: 'Listening' }
  if (h === 'connecting') return { key: 'connecting', label: 'Connecting…' }
  if (h === 'stopping') return { key: 'stopping', label: 'Stopping…' }
  if (h === 'ready') return { key: 'ready', label: 'Ready to listen' }
  if (session.jobStatus === 'blocked') return { key: 'review', label: 'Review required' }
  if (session.jobStatus === 'error') return { key: 'error', label: 'Needs attention' }
  if (session.jobStatus === 'sending') return { key: 'processing', label: 'Sending to SuperDocs…' }
  if (session.jobStatus === 'polling') return { key: 'processing', label: 'SuperDocs editing…' }
  if (session.helper_connected) return { key: 'ready', label: 'Ready to listen' }
  return { key: 'helper-off', label: 'Audio helper not running' }
}

function statusDotClass(key) {
  switch (key) {
    case 'listening': return 'dot live'
    case 'connecting':
    case 'stopping':
    case 'processing': return 'dot work'
    case 'review':
    case 'error': return 'dot attention'
    default: return 'dot ready'
  }
}

function changeVerb(entry) {
  return entry.classification === 'correction' ? 'Corrected' : 'Added'
}

function docSubtitle(sections) {
  // Real data only: if the Project Details table carries a Client value,
  // surface it under the title. Absent → no subtitle, no placeholder.
  const table = sections.find((s) => /<table/i.test(s.bodyHtml))
  if (!table) return ''
  const m = table.bodyHtml.match(/<td><strong>Client<\/strong><\/td><td>([^<]*)<\/td>/i)
  const value = m ? m[1].replace(/&amp;/g, '&').trim() : ''
  return value || ''
}

/* ------------------------------------------------------------------ */
/*  Document section renderer — parses SuperDocs HTML into sections   */
/* ------------------------------------------------------------------ */

function parseSections(html) {
  if (!html) return []
  const sections = []
  const h2Re = /<h2[^>]*>([\s\S]*?)<\/h2>/gi
  let m
  let prevBodyEnd = 0
  while ((m = h2Re.exec(html)) !== null) {
    const bodyStart = m.index + m[0].length
    if (sections.length > 0) {
      sections[sections.length - 1].bodyHtml = html.slice(prevBodyEnd, m.index)
    }
    sections.push({ heading: stripTags(m[1]), bodyHtml: '', text: '' })
    prevBodyEnd = bodyStart
  }
  if (sections.length > 0 && prevBodyEnd > 0) {
    sections[sections.length - 1].bodyHtml = html.slice(prevBodyEnd)
  }
  // bodyText drives the "populated vs empty" decision — a section whose body
  // is only markup (e.g. an empty table) still counts as empty.
  for (const sec of sections) {
    sec.bodyText = stripTags(sec.bodyHtml).trim()
  }
  return sections
}

function stripTags(html) {
  return (html || '').replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').trim()
}

/* ------------------------------------------------------------------ */
/*  Main App                                                          */
/* ------------------------------------------------------------------ */

export default function App() {
  const [status, setStatus] = useState('connecting')
  const [error, setError] = useState(null)
  const [context, setContext] = useState(null)
  const [confirmingClear, setConfirmingClear] = useState(false)
  // null = auto: open while the document is empty, collapsed once it has
  // content. Transcript is secondary; the document is primary.
  const [transcriptOpen, setTranscriptOpen] = useState(null)
  // The card: "Participants see it take shape... and agree the content before
  // anyone leaves." Collaborate puts this panel on every participant's screen,
  // which is the only way that sentence is literally true — otherwise the
  // document is something the host describes rather than something the room
  // watches being written.
  const [collaborating, setCollaborating] = useState(false)
  // The card asks that participants "correct it in the moment". Speaking a
  // correction works — until the transcription is what was wrong, and saying
  // it again is heard wrong again. Typing goes through the identical pipeline
  // (same endpoint, same gate) without depending on the microphone.
  const [correction, setCorrection] = useState('')
  const [highlightIds, setHighlightIds] = useState(new Set())

  useEffect(() => {
    let cancelled = false
    async function connect() {
      try {
        const { runningContext } = await initZoomSdk()
        const joinUrlPromise = isSupported('getMeetingJoinUrl')
          ? getMeetingJoinUrl().then((r) => r?.joinUrl ?? null).catch(() => null)
          : Promise.resolve(null)
        const [meeting, user, uuid, joinUrl] = await Promise.all([
          getMeetingContext(), getUserContext(), getMeetingUUID(), joinUrlPromise,
        ])
        if (cancelled) return
        setContext({ runningContext, meeting, user, uuid, joinUrl })
        setStatus('connected')
      } catch (err) {
        if (cancelled) return
        // Not inside Zoom — a plain browser, or the panel opened outside a
        // meeting. Everything except live audio capture is driven by the
        // meeting id alone, so the product stays fully reviewable here:
        // templates, drafting, the review gate, approval and export all work.
        // Showing a reviewer an error where the app should be would hide a
        // working system behind a missing SDK. `?meeting=<id>` joins a
        // specific session (the demo.py script prints the id it uses).
        const requested = new URLSearchParams(window.location.search).get('meeting')
        setContext({
          runningContext: 'browser',
          meeting: null,
          user: null,
          uuid: { meetingUUID: requested || `demo-${Date.now()}` },
          joinUrl: null,
        })
        setError(err?.message || String(err))
        setStatus('demo')
      }
    }
    connect()
    return () => { cancelled = true }
  }, [])

  const meetingUuid = context?.uuid?.meetingUUID ?? null
  const session = useMeetingSession(meetingUuid)
  // Self-reported attribution, not authentication — same trust level as
  // every other field this app already reads from the Zoom SDK context.
  // Turns "✓ Approved" into "Approved by X", a real reviewer's name instead
  // of an anonymous checkmark.
  const reviewerName = context?.user?.screenName || null
  const showTranscript = transcriptOpen ?? session.draftVersion === 0

  // Track draftVersion to detect new content — brief highlight on the
  // document, not a flash.
  const prevVersion = useRef(session.draftVersion)
  useEffect(() => {
    if (session.draftVersion > 0 && session.draftVersion !== prevVersion.current) {
      prevVersion.current = session.draftVersion
      const hs = new Set()
      hs.add(session.draftVersion)
      setHighlightIds(hs)
      const t = setTimeout(() => setHighlightIds(new Set()), 1800)
      return () => clearTimeout(t)
    }
  }, [session.draftVersion])

  const state = sessionState(session)
  const docLabel = templateLabelOf(session)
  // Control-channel states: Listen shows when idle (helper present or not —
  // a missing helper surfaces the restrained error on click), Stop shows
  // whenever a START/STOP is in flight or ACKed-listening.
  const canListen = state.key === 'ready' || state.key === 'helper-off'
  // Outside Zoom there is no meeting audio to capture and no Mac helper, so
  // Listen cannot do anything. It was still the most prominent control on
  // the page — the first thing a visitor clicks, and a dead end. The notice
  // above explains the situation; the button has to stop contradicting it.
  const outsideZoom = status === 'demo'
  const isListening =
    state.key === 'connecting' || state.key === 'listening' || state.key === 'stopping'

  const sections = session.draftVersion > 0 ? parseSections(session.draftHtml) : []
  const subtitle = sections.length ? docSubtitle(sections) : ''

  return (
    <div className="app">
      {/* ---- Header ---- */}
      <header className="app-header">
        <div className="brand">
          <span className="wordmark">ACCORD</span>
          <span className={statusDotClass(state.key)} aria-hidden="true" />
          <span className="status-label">{state.label}</span>
        </div>
      </header>

      {/* ---- Document tabs (multi-document) ---- */}
      {session.documents && session.documents.length > 0 && (
        <nav className="doc-tabs" aria-label="Documents">
          {session.documents.map((d) => (
            <span key={d.document_id} className={`doc-tab ${d.document_id === session.activeDocumentId ? 'active' : ''}`}>
              <button className="doc-tab-label" onClick={() => session.activateDocument(d.document_id)}>
                {TEMPLATE_LABELS[d.template_key] || 'Document'}
              </button>
              {session.documents.length > 1 && (
                <button className="doc-tab-close" aria-label="Close document" onClick={() => session.deleteDocument(d.document_id)}>
                  ×
                </button>
              )}
            </span>
          ))}
          <select
            className="doc-tab-new"
            value=""
            aria-label="Create new document"
            onChange={(e) => { if (e.target.value) session.createDocument(e.target.value) }}
          >
            <option value="" disabled>+ New</option>
            {Object.entries(TEMPLATE_LABELS).map(([key, label]) => (
              <option key={key} value={key}>{label}</option>
            ))}
          </select>
        </nav>
      )}

      {/* ---- Environment notice (dev browser only) ---- */}
      {status === 'connected' && collaborateSupported() && (
        <div className="collab-bar">
          <span>{collaborating
            ? 'Everyone in the meeting is watching this document.'
            : 'Only you can see this document.'}</span>
          <button className="btn ghost" onClick={async () => {
            const ok = collaborating ? !(await endCollaborate()) : await startCollaborate()
            setCollaborating(collaborating ? !ok : ok)
          }}>
            {collaborating ? 'Stop sharing' : 'Show to participants'}
          </button>
        </div>
      )}

      {status !== 'connected' && (
        <div className="env-notice">
          {status === 'connecting' && 'Connecting…'}
          {status === 'demo' && (
            <>Running outside Zoom — everything works except live audio capture.
            Feed this session a conversation with <code>python3 demo.py</code>.</>
          )}
          {status === 'error' && error}
        </div>
      )}

      {/* ---- Capture strip: one line, one obvious action. Shown once the
             document exists — before that, the empty state owns the
             composition and the listen control. ---- */}
      {session.draftVersion > 0 && (
        <div className={`capture ${state.key}`}>
          <span className="capture-dot" aria-hidden="true" />
          <span className="capture-label">{state.label}</span>
          <span className="capture-action">
            {canListen && !outsideZoom && (
              <button className="btn primary" disabled={session.helperBusy}
                      onClick={() => session.helperStart().catch(() => {})}>
                Listen
              </button>
            )}
            {canListen && outsideZoom && (
              <span className="capture-hint">
                Live capture needs the Zoom panel on a Mac — use <code>demo.py</code>
              </span>
            )}
            {isListening && (
              <button className="btn ghost" disabled={session.helperBusy}
                      onClick={() => session.helperStop().catch(() => {})}>
                Stop
              </button>
            )}
          </span>
        </div>
      )}

      {/* ---- Helper unavailable (restrained, no fake audio claim) ---- */}
      {state.key === 'helper-off' && session.helperError && (
        <div className="session-error">
          <span>{session.helperError}</span>
        </div>
      )}

      {/* ---- Session error (thin, retryable) ---- */}
      {session.error && (
        <div className="session-error">
          <span>
            {session.error}
            {session.pendingBatches > 0 && ` — ${session.pendingBatches} more waiting`}
          </span>
          <button className="btn ghost" onClick={() => session.retryLastBatch()}>
            {session.retrying ? 'Retrying…' : 'Retry'}
          </button>
        </div>
      )}

      {/* ---- HITL review surface ---- */}
      {session.blockingCard && (
        <section className="review" aria-label="Review required">
          <div className="review-rule" aria-hidden="true" />
          <h2 className="eyebrow">Review required</h2>
          <p className="review-reason">{stripTags(session.blockingCard.reason || 'Confirm this change before it is written into the document.')}</p>
          {session.blockingCard.text && (
            /* Without the utterance, a reason like "a correction batch
               touched 5 chunks" gives the reviewer nothing to decide on. */
            <p className="review-quote">“{stripTags(session.blockingCard.text)}”</p>
          )}
          <div className="review-actions">
            <button className="btn primary" onClick={() => session.resolveBlockingCard('accept')}>
              Approve change
            </button>
            <button className="btn ghost" onClick={() => session.resolveBlockingCard('discard')}>
              Discard
            </button>
          </div>
        </section>
      )}

      {/* ---- Document (the hero) ---- */}
      <main className="doc-area">
        {session.draftVersion === 0 ? (
          <EmptyState state={state} canListen={canListen} isListening={isListening}
                      outsideZoom={outsideZoom}
                      templateKey={session.active_template_key} onSetTemplate={session.setTemplate}
                      onUploadTemplate={session.uploadTemplate}
                      customTemplateName={session.customTemplateName}
                      uploadingTemplate={session.uploadingTemplate}
                      onListen={() => session.helperStart().catch(() => {})}
                      onStop={() => session.helperStop().catch(() => {})} />
        ) : (
          <article className={`doc ${highlightIds.has(session.draftVersion) ? 'fresh' : ''}`}>
            <header className="doc-head">
              <h1 className="doc-title">{docLabel}</h1>
              {subtitle && <p className="doc-subtitle">{subtitle}</p>}
            </header>
            {/* A section appears only once it has content, OR while it's the
                one currently being edited (shown as "Drafting…", in its real
                document position) — never the whole template skeleton up
                front. It only ever advances to real content once SuperDocs
                lands a clean result; a rejection just clears activeSection
                without ever showing this section as done. */}
            {sections
              .filter((sec) => sec.bodyText || sec.heading === session.activeSection)
              .map((sec, i) => {
                // A section already holding content showed nothing at all
                // while it was being worked on — so a correction, the one
                // edit a reviewer most wants to watch, happened in silence:
                // the old value simply sat there until the new one replaced
                // it. Mark it as updating WITHOUT touching the body: the
                // committed text stays put and the proposal is still gated,
                // so nothing unvalidated is ever on screen.
                const working = sec.heading === session.activeSection
                return sec.bodyText ? (
                  <section key={i} className={`doc-section${working ? ' updating' : ''}`}>
                    <h3 className="doc-section-label">
                      {sec.heading}
                      {working && <span className="doc-section-working">updating…</span>}
                    </h3>
                    <div className="doc-section-body" dangerouslySetInnerHTML={{ __html: sec.bodyHtml }} />
                  </section>
                ) : (
                  <section key={i} className="doc-section drafting">
                    <h3 className="doc-section-label">{sec.heading}</h3>
                    <p className="doc-section-drafting">Drafting…</p>
                  </section>
                )
              })}
          </article>
        )}
      </main>

      {/* ---- Recent changes ---- */}
      {session.activity.length > 0 && (
        <section className="changes" aria-label="Recent changes">
          <h3 className="eyebrow">Recent changes</h3>
          {session.activity.slice(-4).reverse().map((entry, i) => (
            <div key={i} className={`change-item ${entry.classification}`}>
              <span className="change-verb">{changeVerb(entry)}</span>
              <span className="change-text">{(entry.summary || '').slice(0, 110)}</span>
            </div>
          ))}
        </section>
      )}

      {/* ---- Transcript (secondary, collapsible) ---- */}
      <section className="transcript">
        <button className="transcript-toggle" onClick={() => setTranscriptOpen(!showTranscript)}>
          <span className="toggle-caret" aria-hidden="true">{showTranscript ? '▾' : '▸'}</span>
          Transcript
          <span className="transcript-count">{session.transcriptHistory.length}</span>
        </button>
        {showTranscript && (
          <div className="transcript-body">
            {session.transcriptHistory.length === 0 && (
              <p className="transcript-empty">The conversation will appear here as it unfolds.</p>
            )}
            {session.transcriptHistory.map((event) => (
              <div key={event.sequence} className="transcript-line">
                <span className="transcript-ts">{formatTime(event.timestamp)}</span>
                {event.speaker && <span className="transcript-speaker">{event.speaker}</span>}
                <span className="transcript-text">{event.text}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ---- Completion ---- */}
      {/* Type a correction. Speaking one works, but when the transcription
          itself is wrong — "make it fifty-five thousand" heard as $45,000 —
          repeating it aloud only risks the same mis-hearing. This is the same
          endpoint the microphone feeds, so a typed fact goes through the same
          classifier, the same gate and the same review. */}
      {session.draftVersion > 0 && (
        <form className="correction-bar" onSubmit={(e) => {
          e.preventDefault()
          const text = correction.trim()
          if (!text) return
          setCorrection('')
          session.submitTranscript(text, reviewerName, true).catch(() => {})
        }}>
          <input
            type="text"
            value={correction}
            onChange={(e) => setCorrection(e.target.value)}
            placeholder="Type a correction — e.g. the budget is $55,000"
            aria-label="Type a correction" />
          <button className="btn ghost" type="submit" disabled={!correction.trim() || session.submitting}>
            {session.submitting ? 'Sending…' : 'Correct'}
          </button>
        </form>
      )}

      {session.draftVersion > 0 && (
        session.exportReady ? (
          <section className="completion ready">
            <div className="completion-mark" aria-hidden="true">✓</div>
            <div className="completion-copy">
              <h2 className="completion-title">Ready to send</h2>
              <ul className="completion-checklist">
                <li>Draft complete</li>
                <li>{session.approvedBy ? `Approved by ${session.approvedBy}` : 'No pending changes'}</li>
                <li>Template preserved</li>
                {session.lastExport?.exported_by && <li>Exported by {session.lastExport.exported_by}</li>}
              </ul>
            </div>
            <div className="completion-actions">
              {session.lastExport ? (
                <a className="btn primary" href={session.exportDownloadUrl} download="Meeting-Draft.docx">Download</a>
              ) : (
                <button className="btn primary"
                        onClick={() => session.approveDraft(reviewerName).then(() => session.exportDraft(reviewerName)).catch(() => {})}
                        disabled={session.approving || session.exporting}>
                  {session.exporting ? 'Exporting…' : 'Export document'}
                </button>
              )}
              {/* Downloading leaves the document on one laptop. The link is
                  what gets it to the people who were on the call, while they
                  are still on it — paste it into the meeting chat. */}
              <button className="btn ghost"
                      onClick={() => session.shareDraft().catch(() => {})}
                      disabled={session.sharing}>
                {session.sharing ? 'Creating link…' : 'Share with participants'}
              </button>
            </div>
            {session.shareUrl && (
              <p className="share-url">
                Link copied — paste it into the meeting chat.
                <code title={session.shareUrl}>{session.shareUrl}</code>
              </p>
            )}
            {session.shareError && <p className="share-error">{session.shareError}</p>}
          </section>
        ) : (
          <section className="completion pending">
            <div className="completion-copy">
              {/* Approving and then being shown "ready for review" again reads
                  as the button not working. It is actually a straggler batch
                  landing after the approval, which correctly invalidates it —
                  say THAT, so a reviewer mid-meeting knows the difference
                  between "not approved yet" and "approved, then it moved". */}
              <h2 className="completion-title">
                {session.approvedDraftVersion
                  ? 'Changed since you approved'
                  : 'Draft ready for review'}
              </h2>
              <p className="completion-detail">
                {session.approvedDraftVersion
                  ? 'More was said after you approved, so the document moved on. Approve again to send this version.'
                  : `${session.activity.length - (session.approvedDraftVersion || 0)} change${session.activity.length - (session.approvedDraftVersion || 0) === 1 ? '' : 's'} since last review`}
              </p>
            </div>
            <button className="btn ghost" onClick={() => session.approveDraft(reviewerName).catch(() => {})} disabled={session.approving}>
              {session.approving ? 'Approving…' : (session.approvedDraftVersion ? 'Approve again' : 'Approve draft')}
            </button>
          </section>
        )
      )}

      {/* ---- Clear meeting data — always visible, own in-app confirm.
             window.confirm() is unreliable inside Zoom's embedded webview
             (blocking dialogs can silently no-op there), so this never
             depends on one. ---- */}
      <div className="dev">
        {confirmingClear ? (
          <>
            <span className="dev-label">Clear all meeting data?</span>
            <button
              className="btn primary"
              onClick={() => { setConfirmingClear(false); session.clearMeetingData() }}
              disabled={session.clearing}
            >
              {session.clearing ? 'Clearing…' : 'Yes, clear'}
            </button>
            <button className="btn ghost" onClick={() => setConfirmingClear(false)}>
              Cancel
            </button>
          </>
        ) : (
          <button className="btn ghost" onClick={() => setConfirmingClear(true)}>
            Clear meeting data
          </button>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/*  Empty state — the first thing a participant sees                 */
/* ------------------------------------------------------------------ */

function EmptyState({ state, canListen, isListening, outsideZoom, templateKey, onSetTemplate,
                     onUploadTemplate, customTemplateName, uploadingTemplate,
                     onListen, onStop }) {
  const ready = state.key === 'ready'
  return (
    <div className="empty">
      <div className="empty-brand">ACCORD</div>
      <p className="empty-tagline">
        Your document is being prepared<br />as the conversation unfolds.
      </p>
      {/* Chosen once, before anything is drafted — free to change here since
          nothing has been sent to SuperDocs yet. Disappears once the first
          section lands (the doc view takes over), matching "select
          template, then participants speak, then it builds." */}
      <select
        className="empty-template-select"
        value={templateKey || 'statement_of_work'}
        aria-label="Document type"
        onChange={(e) => onSetTemplate(e.target.value)}
      >
        {Object.entries(TEMPLATE_LABELS).map(([key, label]) => (
          <option key={key} value={key}>{label}</option>
        ))}
      </select>
      {/* The firm's own document, uploaded as-is, so the deliverable comes
          back on their letterhead and section structure rather than ours. */}
      <label className="empty-upload">
        <input
          type="file"
          accept=".docx"
          onChange={(e) => {
            const file = e.target.files && e.target.files[0]
            if (file) onUploadTemplate(file)
            e.target.value = ''
          }}
        />
        <span>
          {uploadingTemplate
            ? 'Reading your template…'
            : customTemplateName
              ? `Using ${customTemplateName}`
              : 'Use your own template (.docx)'}
        </span>
      </label>
      <div className="empty-status">
        <span className={`capture-dot ${state.key}`} aria-hidden="true" />
        <span>{state.label}</span>
      </div>
      {canListen && outsideZoom ? (
        <p className="empty-hint">
          Live capture needs the Zoom panel on a Mac. To watch this document
          build, run <code>python3 demo.py</code> against this session.
        </p>
      ) : (
        <>
          {ready && canListen && (
            <button className="btn primary empty-listen" onClick={onListen}>Listen</button>
          )}
          {canListen && state.key === 'helper-off' && (
            <button className="btn primary empty-listen" onClick={onListen}>Listen</button>
          )}
        </>
      )}
      {isListening && (
        <button className="btn ghost empty-listen" onClick={onStop}>Stop</button>
      )}
    </div>
  )
}

function formatTime(timestamp) {
  return new Date(timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
