// The only module in this app that imports @zoom/appssdk directly (design
// doc §11). Every screen goes through this, not the SDK — the same reason
// the backend's TranscriptProvider exists: callers shouldn't need to know
// which capabilities actually got granted, only what this module reports.
//
// Milestone 4 adds the 5 RTMS capabilities — already granted on the
// Marketplace app since M0 (PROGRESS.md), unused here until now per the
// least-privilege note (A5): App.jsx is the first real caller (see its
// gated startRTMS() trigger).
import zoomSdk from '@zoom/appssdk'

const CAPABILITIES = [
  'getSupportedJsApis',
  'getRunningContext',
  'getMeetingContext',
  'getMeetingJoinUrl',
  'getUserContext',
  'getMeetingUUID',
  'startRTMS',
  'stopRTMS',
  'getRTMSStatus',
  'pauseRTMS',
  'resumeRTMS',
]

// The assigned build's card asks that "participants see it take shape... and
// agree the content before anyone leaves". Collaborate is what makes that
// literally true: it puts this panel on every participant's screen instead of
// only the host's.
//
// Requested SEPARATELY because getSupportedJsApis() only ever reports back
// capabilities that were asked for (PROGRESS.md, M0) — the only way to learn
// whether an app is entitled to collaborate is to request it. And requested
// with a fallback because a config() that rejects one ungranted capability
// would otherwise take the whole panel down with it, dropping a real meeting
// into browser-demo mode.
const OPTIONAL_CAPABILITIES = [
  'startCollaborate',
  'endCollaborate',
  'getMeetingParticipants',
]

let configured = null

// Idempotent — React.StrictMode double-invokes effects in dev, and a second
// zoomSdk.config() call is wasted work at best.
export async function initZoomSdk() {
  if (configured) return configured
  let configResponse
  let requested = [...CAPABILITIES, ...OPTIONAL_CAPABILITIES]
  try {
    configResponse = await zoomSdk.config({ version: '0.16', capabilities: requested })
  } catch (err) {
    // Not entitled to one of the optional capabilities. Fall back to the set
    // that has always worked rather than losing the panel — the collaborate
    // features simply stay hidden, and `collaborateUnavailable` records why
    // so the UI can say so honestly instead of silently missing a button.
    console.warn('Zoom config rejected the optional capabilities:', err?.message || err)
    requested = CAPABILITIES
    configResponse = await zoomSdk.config({ version: '0.16', capabilities: requested })
    configured = { collaborateUnavailable: err?.message || String(err) }
  }
  const supported = await zoomSdk.getSupportedJsApis()
  configured = {
    ...(configured || {}),
    runningContext: configResponse.runningContext,
    supportedApis: supported.supportedApis || [],
  }
  return configured
}

// Put the panel on every participant's screen. Returns false when the app is
// not entitled — never throws, because "participants cannot see this" is a
// degraded state, not a crash.
export async function startCollaborate() {
  if (!isSupported('startCollaborate')) return false
  try {
    await zoomSdk.startCollaborate()
    return true
  } catch (err) {
    console.warn('startCollaborate failed:', err?.message || err)
    return false
  }
}

export async function endCollaborate() {
  if (!isSupported('endCollaborate')) return false
  try {
    await zoomSdk.endCollaborate()
    return true
  } catch { return false }
}

export function collaborateSupported() {
  return isSupported('startCollaborate')
}

export function isSupported(api) {
  return configured?.supportedApis.includes(api) ?? false
}

export function getMeetingContext() {
  return zoomSdk.getMeetingContext()
}

// Milestone 6 — the password-bearing join link for the CURRENT meeting
// (Zoom SDK: GetMeetingJoinUrlResponse = { joinUrl }). Passed through to
// Vexa as meeting_url so a passcode-protected meeting can be joined; the
// URL is resolved fresh on every Start listening click — nothing about a
// meeting's identity is ever hardcoded or persisted.
export function getMeetingJoinUrl() {
  return zoomSdk.getMeetingJoinUrl()
}

export function getUserContext() {
  return zoomSdk.getUserContext()
}

export function getMeetingUUID() {
  return zoomSdk.getMeetingUUID()
}

export function startRTMS() {
  return zoomSdk.startRTMS()
}

export function stopRTMS() {
  return zoomSdk.stopRTMS()
}

export function getRTMSStatus() {
  return zoomSdk.getRTMSStatus()
}

// Exported for interface completeness, matching the backend provider's own
// scope note — no panel control calls these in M4; nothing in this
// milestone needs an off-the-record pause affordance.
export function pauseRTMS() {
  return zoomSdk.pauseRTMS()
}

export function resumeRTMS() {
  return zoomSdk.resumeRTMS()
}
