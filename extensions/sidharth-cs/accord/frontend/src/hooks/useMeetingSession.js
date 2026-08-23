import { useCallback, useEffect, useRef, useState } from 'react'

const BLANK = {
  jobStatus: 'idle',
  error: null,
  draftHtml: '',
  transcriptHistory: [],
  activity: [],
  blockingCard: null,
  provider: null,
  draftVersion: 0,
  approvedDraftVersion: null,
  approvedBy: null,
  lastExport: null,
  documents: [],
  activeDocumentId: null,
  active_template_key: 'statement_of_work',
  helper_status: 'disconnected',
  helper_connected: false,
  activeSection: null,
  pendingBatches: 0,
  customTemplateName: null,
}

// Milestone 4: provider.status only passes through "connecting" for a
// bounded window (RTMSTranscriptProvider's own 20s connect watchdog) —
// ManualTranscriptProvider goes NOT_STARTED -> LIVE synchronously in
// start(), so this poll never even begins for the manual (real deployed
// default) path. Deliberately not SSE: a one-time, ≤20s, once-per-meeting
// need doesn't earn a new server-push event type — see the plan's own
// "surfacing status" section.
const PROVIDER_POLL_MS = 2500

// Zoom meeting UUIDs are base64-shaped and routinely contain /, +, = (real
// example seen live: "QkxusPH6QZm9FEK/fVQB/Q=="). A raw / breaks path
// routing even percent-encoded — confirmed directly against this app's own
// backend that %2F still 404s, since meeting_uuid isn't the route's final
// segment. base64url-encoding here never produces /, sidestepping the
// problem instead of fighting the framework; the backend decodes it back
// (app/api/encoding.py) before use. See PROGRESS.md M3.
function encodeMeetingUuid(uuid) {
  return btoa(uuid).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

// Combines what the design doc splits into useMeetingSession + useLiveEvents
// (§11) into one hook — M3 is a single panel with one state shape, not two
// concerns that earn separate files yet. State only ever moves forward from
// the backend's SSE stream (§11: no optimistic local mutation); submitTranscript
// posts and waits — the stream is what actually updates state, same reasoning
// as the backend never trusting its own guess over SuperDocs' returned HTML.

export function useMeetingSession(meetingUuid) {
  const [state, setState] = useState(BLANK)
  const [connected, setConnected] = useState(false)
  const [reconnectVisible, setReconnectVisible] = useState(false)
  const reconnectTimer = useRef(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [approving, setApproving] = useState(false)
  const [approveError, setApproveError] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState(null)

  // Milestone 6 — the explicit Start/Stop listening lifecycle (Vexa). The
  // POST response carries the resulting provider status, but like every
  // other mutation in this app the panel's own state advances via the /state
  // poll and the provider-status poll below — the response is a fast-fail
  // signal, not the source of truth.
  const [startingListening, setStartingListening] = useState(false)
  const [stoppingListening, setStoppingListening] = useState(false)
  const [listenError, setListenError] = useState(null)

  const startListening = useCallback(
    async (meetingNumber, meetingUrl, passcode) => {
      setStartingListening(true)
      setListenError(null)
      try {
        const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/listen`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            meeting_number: meetingNumber || null,
            // The SDK's join link for the CURRENT meeting (includes ?pwd=
            // when the meeting has a passcode). Resolved fresh per click —
            // never stored or reused across meetings.
            meeting_url: meetingUrl || null,
            // Ephemeral per-attempt passcode (only present when the panel
            // was asked for one after Vexa reported passcode_required).
            passcode: passcode || undefined,
          }),
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || `Request failed (${res.status})`)
        }
        // Milestone 6 fix: the response's provider status IS the state
        // transition — nothing else advances state.provider.status from
        // not_started (the /state poll below only runs once status is
        // already "connecting", and SSE has no provider-status event), so
        // discarding the body left the panel stuck on "Start listening"
        // while the backend had already started the bot. Applying it here
        // also arms the existing provider-status poll for the rest of the
        // lifecycle (connecting → live).
        const body = await res.json().catch(() => ({}))
        if (body?.status) {
          setState((prev) => ({
            ...prev,
            provider: { name: prev.provider?.name ?? 'vexa', status: body.status },
          }))
        }
      } catch (err) {
        setListenError(err.message || String(err))
        throw err
      } finally {
        setStartingListening(false)
      }
    },
    [meetingUuid]
  )

  const stopListening = useCallback(async () => {
    setStoppingListening(true)
    setListenError(null)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/listen/stop`, {
        method: 'POST',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${res.status})`)
      }
      // Same fix as startListening: apply the returned status ("stopped")
      // so the panel returns to the Start-listening state instead of
      // silently keeping the old one.
      const body = await res.json().catch(() => ({}))
      if (body?.status) {
        setState((prev) => ({
          ...prev,
          provider: { name: prev.provider?.name ?? 'vexa', status: body.status },
        }))
      }
    } catch (err) {
      setListenError(err.message || String(err))
      throw err
    } finally {
      setStoppingListening(false)
    }
  }, [meetingUuid])

  // Control channel (Architecture B spike): Listen/Stop route the command to
  // the Mac helper through the backend's helper registry. The status is only
  // advanced by the helper's ACK (SSE helper_status event), never claimed
  // optimistically.
  const [helperBusy, setHelperBusy] = useState(false)
  const [helperError, setHelperError] = useState(null)
  const helperStart = useCallback(async () => {
    setHelperBusy(true)
    setHelperError(null)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/helper/start`, {
        method: 'POST',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${res.status})`)
      }
    } catch (err) {
      setHelperError(err.message || String(err))
      throw err
    } finally {
      setHelperBusy(false)
    }
  }, [meetingUuid])

  const helperStop = useCallback(async () => {
    setHelperBusy(true)
    setHelperError(null)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/helper/stop`, {
        method: 'POST',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${res.status})`)
      }
    } catch (err) {
      setHelperError(err.message || String(err))
      throw err
    } finally {
      setHelperBusy(false)
    }
  }, [meetingUuid])

  useEffect(() => {
    if (!meetingUuid) return
    let cancelled = false
    setState(BLANK)
    const encodedUuid = encodeMeetingUuid(meetingUuid)

    async function loadInitialState() {
      const res = await fetch(`/api/meetings/${encodedUuid}/state`)
      if (!res.ok || cancelled) return
      const data = await res.json()
      if (cancelled) return
      setState({
        jobStatus: data.job_status,
        error: data.error,
        draftHtml: data.current_draft_html,
        transcriptHistory: data.transcript_history,
        activity: data.activity,
        // Rebuilt from the snapshot, never blanked: a blocking card is the
        // one state that requires a human, and hard-coding null here meant
        // every reload silently discarded it while the server stayed
        // blocked.
        blockingCard: data.blocking_card
          ? { reason: data.blocking_card.reason, text: data.blocking_card.text || null }
          : null,
        provider: data.provider || null,
        draftVersion: data.draft_version,
        approvedDraftVersion: data.approved_draft_version,
        approvedBy: data.approved_by || null,
        lastExport: data.last_export || null,
        documents: data.documents || [],
        activeDocumentId: data.active_document_id || null,
        active_template_key: data.active_template_key || 'statement_of_work',
        helper_status: data.helper_status || 'disconnected',
        helper_connected: !!data.helper_connected,
        activeSection: data.active_section || null,
        pendingBatches: data.pending_batches || 0,
        customTemplateName: data.custom_template_name || null,
      })
    }
    loadInitialState()

    // Browser's own auto-reconnect-on-drop covers the reconnect case; a
    // panel reload re-runs this effect from scratch and refetches state
    // above, so nothing here needs to survive a reload itself (§21: the
    // panel holds no state the backend doesn't already have).
    const source = new EventSource(`/api/meetings/${encodedUuid}/events`)
    source.onopen = () => {
      setConnected(true)
      setReconnectVisible(false)
      if (reconnectTimer.current) { clearTimeout(reconnectTimer.current); reconnectTimer.current = null }
      // Re-fetch /state on reconnect to catch events missed during gap
      loadInitialState()
    }
    source.onerror = () => {
      setConnected(false)
      // Delay reconnect message by 500ms to avoid flash on brief drops
      if (!reconnectTimer.current) {
        reconnectTimer.current = setTimeout(() => setReconnectVisible(true), 500)
      }
    }
    source.onmessage = (msg) => {
      const event = JSON.parse(msg.data)
      if (event.type === 'transcript_received') {
        console.log('[SSE] transcript_received:', event.event?.text?.substring(0,40), 'seq=', event.event?.sequence)
      }
      setState((prev) => {
        const next = applyEvent(prev, event)
        if (event.type === 'transcript_received') {
          console.log('[SSE] transcriptHistory length:', next.transcriptHistory?.length,
            'entries:', next.transcriptHistory?.map(e => e.text?.substring(0,20)))
        }
        return next
      })
    }

    return () => {
      cancelled = true
      source.close()
    }
  }, [meetingUuid])

  useEffect(() => {
    if (!meetingUuid || state.provider?.status !== 'connecting') return
    const encodedUuid = encodeMeetingUuid(meetingUuid)
    let cancelled = false
    const pollId = setInterval(async () => {
      const res = await fetch(`/api/meetings/${encodedUuid}/state`)
      if (!res.ok || cancelled) return
      const data = await res.json()
      if (cancelled) return
      setState((prev) => ({ ...prev, provider: data.provider || null }))
    }, PROVIDER_POLL_MS)
    return () => {
      cancelled = true
      clearInterval(pollId)
    }
  }, [meetingUuid, state.provider?.status])

  const submitTranscript = useCallback(
    async (text, speaker, isCorrection) => {
      setSubmitting(true)
      setSubmitError(null)
      try {
        const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/transcript`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, speaker: speaker || null, is_correction: !!isCorrection }),
        })
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || `Request failed (${res.status})`)
        }
      } catch (err) {
        setSubmitError(err.message || String(err))
        throw err
      } finally {
        setSubmitting(false)
      }
    },
    [meetingUuid]
  )

  // Empty-state template choice — before the first batch lands, switching
  // template is free (nothing's been sent to SuperDocs yet); the backend's
  // set_active_template() already re-renders the starter for a fresh doc.
  const setTemplate = useCallback(async (templateKey) => {
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/template`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_key: templateKey }),
      })
      if (res.ok) {
        const data = await res.json()
        // `documents` carries each tab's own template_key, and the tab label
        // reads from it — updating only active_template_key left the tab
        // showing the previous template's name after a switch.
        setState(prev => ({
          ...prev,
          active_template_key: data.active_template_key,
          documents: data.documents || prev.documents,
          activeDocumentId: data.active_document_id || prev.activeDocumentId,
          draftHtml: data.current_draft_html ?? prev.draftHtml,
          draftVersion: data.draft_version ?? prev.draftVersion,
        }))
      }
    } catch { /* SSE will update */ }
  }, [meetingUuid])

  // The firm's own .docx becomes the starting document, so the deliverable
  // comes back on their letterhead and section structure. Read in the
  // browser and sent as base64 — the backend hands it to SuperDocs
  // untouched rather than trying to parse Word itself.
  const [uploadingTemplate, setUploadingTemplate] = useState(false)
  const uploadTemplate = useCallback(async (file) => {
    setUploadingTemplate(true)
    try {
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader()
        reader.onload = () => resolve(String(reader.result).split(',')[1] || '')
        reader.onerror = () => reject(reader.error)
        reader.readAsDataURL(file)
      })
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/template/upload`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_base64: base64, filename: file.name }),
      })
      if (res.ok) {
        const data = await res.json()
        setState((prev) => ({
          ...prev,
          draftHtml: data.current_draft_html ?? prev.draftHtml,
          draftVersion: data.draft_version ?? prev.draftVersion,
          customTemplateName: data.custom_template_name || file.name,
          error: null,
        }))
      } else {
        const detail = await res.json().catch(() => null)
        setState((prev) => ({
          ...prev,
          error: detail?.detail || 'That document could not be read.',
        }))
      }
    } catch (err) {
      setState((prev) => ({ ...prev, error: 'That document could not be read.' }))
    } finally {
      setUploadingTemplate(false)
    }
  }, [meetingUuid])

  // Phase 3 — document management
  const [creatingDoc, setCreatingDoc] = useState(false)
  const createDocument = useCallback(async (templateKey) => {
    setCreatingDoc(true)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/documents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_key: templateKey }),
      })
      if (res.ok) {
        const data = await res.json()
        setState(prev => ({
          ...prev,
          documents: data.documents || [],
          activeDocumentId: data.active_document_id,
          draftHtml: data.current_draft_html,
          draftVersion: data.draft_version,
          approvedDraftVersion: data.approved_draft_version,
          activity: data.activity,
          lastExport: data.last_export,
          active_template_key: data.active_template_key,
        }))
      }
    } catch { /* SSE will update */ }
    finally { setCreatingDoc(false) }
  }, [meetingUuid])

  const activateDocument = useCallback(async (documentId) => {
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/documents/${documentId}/activate`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setState(prev => ({
          ...prev,
          documents: data.documents || [],
          activeDocumentId: data.active_document_id,
          draftHtml: data.current_draft_html,
          draftVersion: data.draft_version,
          approvedDraftVersion: data.approved_draft_version,
          activity: data.activity,
          lastExport: data.last_export,
          active_template_key: data.active_template_key,
        }))
      }
    } catch { /* SSE will update */ }
  }, [meetingUuid])

  const deleteDocument = useCallback(async (documentId) => {
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/documents/${encodeURIComponent(documentId)}`, { method: 'DELETE' })
      if (res.ok) {
        const data = await res.json()
        setState(prev => ({
          ...prev,
          documents: data.documents || [],
          activeDocumentId: data.active_document_id,
          draftHtml: data.current_draft_html,
          draftVersion: data.draft_version,
          approvedDraftVersion: data.approved_draft_version,
          activity: data.activity,
          lastExport: data.last_export,
          active_template_key: data.active_template_key,
        }))
      }
    } catch { /* SSE will update */ }
  }, [meetingUuid])

  // Milestone 5. Does not mutate `state` on success — same "no optimistic
  // local mutation" policy as submitTranscript above; the draft_approved
  // SSE echo is what actually advances approvedDraftVersion.
  const approveDraft = useCallback(async (approverName) => {
    setApproving(true)
    setApproveError(null)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ draft_version: state.draftVersion, approver: approverName || null }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed (${res.status})`)
      }
    } catch (err) {
      setApproveError(err.message || String(err))
      throw err
    } finally {
      setApproving(false)
    }
  }, [meetingUuid, state.draftVersion])

  // Follow-up fix (see PROGRESS.md): the old version read the response as a
  // Blob and fired a programmatic <a>.click() — invisible if it worked,
  // silent if it didn't. A Zoom in-meeting panel is an embedded webview,
  // not Chrome/Safari; there is no reliable way for JS to confirm a
  // programmatic download actually landed anywhere the user can find it.
  // So this call now only confirms the export itself succeeded (real
  // SuperDocs bytes exist, server-side) — it does not attempt to trigger a
  // download at all. The actual retrieval is a real, visible, user-clicked
  // <a href> pointing at GET .../export/download (App.jsx), a plain
  // navigable URL the embedded webview's own native download handling is
  // far more likely to honor than JS-driven Blob/ObjectURL choreography,
  // and — same as submitTranscript/approveDraft above — this does not
  // locally set `state`; the export_completed SSE echo does that, so
  // `session.lastExport` (and therefore the download link) only ever
  // reflects what the backend actually confirms happened.
  // The card asks for the document to be "finished and sent while the call is
  // still open". Export writes a file to this operator's own disk, which
  // reaches nobody — so the link is what actually closes that: mint it, copy
  // it, paste it into the meeting chat, and everyone has the document before
  // they leave.
  const [shareUrl, setShareUrl] = useState(null)
  const [sharing, setSharing] = useState(false)
  const [shareError, setShareError] = useState(null)

  const shareDraft = useCallback(async () => {
    setSharing(true)
    setShareError(null)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/share`, {
        method: 'POST',
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Could not create a link (${res.status})`)
      }
      const { url } = await res.json()
      setShareUrl(url)
      // Clipboard is best-effort: it needs a secure context and permission,
      // and the link is shown on screen either way so a refusal costs nothing.
      try { await navigator.clipboard.writeText(url) } catch { /* shown below */ }
      return url
    } catch (err) {
      setShareError(err.message || String(err))
      throw err
    } finally {
      setSharing(false)
    }
  }, [meetingUuid])

  const exportDraft = useCallback(async (exporterName) => {
    setExporting(true)
    setExportError(null)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ exporter: exporterName || null }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Export failed (${res.status})`)
      }
    } catch (err) {
      setExportError(err.message || String(err))
      throw err
    } finally {
      setExporting(false)
    }
  }, [meetingUuid])

  const exportDownloadUrl = meetingUuid
    ? `/api/meetings/${encodeMeetingUuid(meetingUuid)}/export/download`
    : null

  // Derived, not stored — same discipline as the backend's export_ready
  // property; two numbers already in state can't desync from themselves.
  const exportReady = state.approvedDraftVersion !== null && state.approvedDraftVersion === state.draftVersion

  const [clearing, setClearing] = useState(false)
  const clearMeetingData = useCallback(async () => {
    setClearing(true)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/clear`, { method: 'POST' })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Clear failed (${res.status})`)
      }
      const snapshot = await res.json()
      setState({
        jobStatus: snapshot.job_status,
        error: snapshot.error,
        draftHtml: snapshot.current_draft_html,
        transcriptHistory: snapshot.transcript_history,
        activity: snapshot.activity,
        blockingCard: snapshot.blocking_card
          ? { reason: snapshot.blocking_card.reason, text: snapshot.blocking_card.text || null }
          : null,
        provider: snapshot.provider || null,
        draftVersion: snapshot.draft_version,
        approvedDraftVersion: snapshot.approved_draft_version,
        approvedBy: snapshot.approved_by || null,
        lastExport: snapshot.last_export || null,
        documents: snapshot.documents || [],
        activeDocumentId: snapshot.active_document_id || null,
        active_template_key: snapshot.active_template_key || 'statement_of_work',
        activeSection: snapshot.active_section || null,
      })
    } catch (err) {
      setSubmitError(err.message || String(err))
    } finally {
      setClearing(false)
    }
  }, [meetingUuid])

  // retry / blocking-card actions
  const [retrying, setRetrying] = useState(false)
  const retryLastBatch = useCallback(async () => {
    setRetrying(true)
    try {
      const res = await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/retry`, { method: 'POST' })
      if (res.ok) {
        const data = await res.json()
        setState((prev) => ({ ...prev, error: data.error, pendingBatches: data.pending_batches || 0 }))
      }
    } finally {
      setRetrying(false)
    }
  }, [meetingUuid])

  const resolveBlockingCard = useCallback(async (action) => {
    try {
      await fetch(`/api/meetings/${encodeMeetingUuid(meetingUuid)}/blocking-card/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
    } catch { /* SSE will update state */ }
  }, [meetingUuid])

  return {
    ...state,
    connected,
    reconnectVisible,
    submitting,
    submitError,
    submitTranscript,
    exportReady,
    approving,
    approveError,
    approveDraft,
    exporting,
    exportError,
    exportDraft,
    exportDownloadUrl,
    shareDraft,
    shareUrl,
    sharing,
    shareError,
    startingListening,
    stoppingListening,
    listenError,
    startListening,
    stopListening,
    clearing,
    clearMeetingData,
    retrying,
    retryLastBatch,
    resolveBlockingCard,
    creatingDoc,
    createDocument,
    setTemplate,
    uploadTemplate,
    uploadingTemplate,
    activateDocument,
    deleteDocument,
    helperStart,
    helperStop,
    helperBusy,
    helperError,
  }
}

function applyEvent(prev, event) {
  switch (event.type) {
    case 'session_reset':
      return {
        ...BLANK,
        provider: prev.provider,
        documents: event.documents || [],
        activeDocumentId: event.active_document_id || null,
        active_template_key: event.active_template_key || 'statement_of_work',
      }
    case 'transcript_received':
      return { ...prev, transcriptHistory: [...prev.transcriptHistory, event.event] }
    case 'job_status':
      // Only a status that is no longer 'blocked' clears the card. This
      // used to null it unconditionally, so any later status event — an
      // export, a cleanup pass — erased a card the server still had
      // pending, leaving the panel healthy and the document diverged.
      return event.status === 'blocked'
        ? { ...prev, jobStatus: event.status }
        : { ...prev, jobStatus: event.status, blockingCard: null, error: null }
    case 'draft_updated':
      return { ...prev, draftHtml: event.html, draftVersion: event.draft_version, error: null }
    case 'activity':
      return { ...prev, activity: [...prev.activity, event.entry] }
    case 'blocking_card':
      return { ...prev, blockingCard: { reason: event.reason, text: event.text || null } }
    case 'draft_approved':
      return { ...prev, approvedDraftVersion: event.draft_version, approvedBy: event.approved_by || null }
    case 'export_completed':
      return {
        ...prev,
        lastExport: {
          content_type: event.content_type,
          size: event.size,
          exported_at: event.exported_at,
          exported_by: event.exported_by || null,
        },
      }
    case 'error':
      return {
        ...prev,
        error: event.message,
        pendingBatches: event.pending_batches ?? prev.pendingBatches,
      }
    case 'helper_status':
      return { ...prev, helper_status: event.status }
    case 'active_section':
      return { ...prev, activeSection: event.section }
    default:
      return prev
  }
}
