const statusEl = document.getElementById('status');
const logEl = document.getElementById('log');
const startBtn = document.getElementById('start-btn');

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = 'status-' + kind;
}

function log(label, value) {
  const line = `[${new Date().toLocaleTimeString()}] ${label} ${value !== undefined ? JSON.stringify(value) : ''}`;
  logEl.textContent = logEl.textContent === 'waiting…' ? line : logEl.textContent + '\n' + line;
}

async function init() {
  if (typeof zoomSdk === 'undefined') {
    setStatus('zoomSdk not found — this page must be opened inside Zoom, not a plain browser tab.', 'err');
    return;
  }

  try {
    // The 5 already-approved APIs plus the 4 new RTMS ones this milestone
    // needs. Requesting a capability the Marketplace app hasn't been
    // granted yet doesn't crash config() — it just means calling that API
    // later will fail, which is exactly what this spike is here to find out.
    const configResponse = await zoomSdk.config({
      version: '0.16',
      capabilities: [
        'getSupportedJsApis',
        'getRunningContext',
        'getMeetingContext',
        'getUserContext',
        'getMeetingUUID',
        'startRTMS',
        'pauseRTMS',
        'resumeRTMS',
        'getRTMSStatus',
      ],
    });
    log('config() ok, runningContext =', configResponse.runningContext);

    const supported = await zoomSdk.getSupportedJsApis();
    // The real field on the SDK's response object is `supportedApis`, not
    // `supportedJsApis` — confirmed by relaying the raw, unfiltered response
    // to the backend log (see PROGRESS.md). Reading the wrong key silently
    // produced `undefined`, which the `|| []` fallback below turned into an
    // always-empty array — startRTMS was present the whole time, granted
    // correctly, this check just never looked at the right property.
    log('getSupportedJsApis ->', supported.supportedApis);

    const hasRTMS = (supported.supportedApis || []).includes('startRTMS');
    if (!hasRTMS) {
      setStatus('startRTMS is not in getSupportedJsApis() — add RTMS scopes/capabilities in the Marketplace app config first.', 'err');
      return;
    }

    const meetingUUID = await zoomSdk.getMeetingUUID();
    log('getMeetingUUID ->', meetingUUID);

    setStatus('Ready — click Start, then watch the backend log for meeting.rtms_started.', 'ok');
    startBtn.disabled = false;
  } catch (err) {
    setStatus('zoomSdk.config() failed: ' + err.message, 'err');
    log('config() error', err.message);
  }
}

startBtn.addEventListener('click', async () => {
  startBtn.disabled = true;
  setStatus('startRTMS() called — waiting up to 20s for the webhook…', 'pending');
  try {
    const result = await zoomSdk.startRTMS();
    log('startRTMS() resolved ->', result);
    setStatus('startRTMS() resolved. Check the backend terminal for meeting.rtms_started — that webhook is the actual pass/fail signal, not this line.', 'ok');
  } catch (err) {
    log('startRTMS() rejected ->', err.message || err);
    setStatus('startRTMS() rejected: ' + (err.message || err), 'err');
  } finally {
    startBtn.disabled = false;
  }
});

init();
