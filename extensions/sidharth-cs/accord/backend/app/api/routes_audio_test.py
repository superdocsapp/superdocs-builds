"""Diagnostic route — standalone HTML page testing browser media APIs inside
the Zoom App webview.  Static-first UI: all controls in HTML, JS updates
progressively.  ES5-only JavaScript (no async/await, no arrow functions, no
const/let) for maximum webview compatibility.  No recordings leave the browser."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_AUDIO_TEST_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Audio Diagnostic</title>
<style>
body{font:13px/1.4 -apple-system,sans-serif;padding:12px;color:#1a1a1a;background:#fff}
h2{font-size:14px;margin:16px 0 4px;border-top:1px solid #e0e0e0;padding-top:12px}
.pass{color:#1e7e34}.fail{color:#c5221f}.info{color:#5f6368}.warn{color:#916a00}
button{font:inherit;padding:6px 14px;margin:4px 8px 4px 0;cursor:pointer;border:1px solid #1a3a5a;border-radius:4px;background:#1a3a5a;color:#fff}
button:disabled{opacity:0.4;cursor:default}
button.secondary{background:#fff;color:#1a3a5a}
.stat{display:flex;align-items:baseline;gap:4px;margin:2px 0;font-size:12px}
.stat-label{color:#888;min-width:120px}
</style>
</head>
<body>
<h1>Audio Diagnostic</h1>
<p style="color:#5f6368;font-size:12px;margin:0 0 12px">Tests whether browser media APIs inside the Zoom App webview can access remote meeting audio. No recordings leave your browser.</p>

<!-- ====== STATIC UI — always visible, JS updates values ====== -->

<h2>1. Status</h2>
<div class="stat"><span class="stat-label">Page loaded</span><span id="s-page">Yes</span></div>
<div class="stat"><span class="stat-label">JS initialized</span><span id="s-js" class="warn">Waiting...</span></div>
<div class="stat"><span class="stat-label">User agent</span><span id="s-ua" style="font-size:10px;word-break:break-all">-</span></div>

<h2>2. Browser Media APIs</h2>
<div class="stat"><span class="stat-label">mediaDevices</span><span id="s-md" class="warn">Checking...</span></div>
<div class="stat"><span class="stat-label">getUserMedia</span><span id="s-gum" class="warn">Checking...</span></div>
<div class="stat"><span class="stat-label">getDisplayMedia</span><span id="s-gdm" class="warn">Checking...</span></div>
<div class="stat"><span class="stat-label">MediaRecorder</span><span id="s-mr" class="warn">Checking...</span></div>
<div class="stat"><span class="stat-label">AudioContext</span><span id="s-ac" class="warn">Checking...</span></div>

<h2>3. Audio Devices</h2>
<div id="devices"><span class="info">Not yet checked.</span></div>
<button id="btn-enum" class="secondary" onclick="enumerateDevices()">Enumerate Devices</button>

<h2>4. Microphone Test</h2>
<p style="font-size:11px;color:#888;margin:4px 0">Requires user click. 10-second timeout prevents hanging if Zoom webview blocks the permission dialog.</p>
<button id="btn-mic" onclick="requestMicrophone()">Request Microphone Access</button>
<span id="mic-status" style="font-size:12px;margin-left:8px"></span>

<h2>5. Recording Test</h2>
<p style="font-size:11px;color:#888;margin:4px 0">Records 3 seconds. To test remote audio: mute yourself in Zoom, have another participant speak.</p>
<button id="btn-rec" disabled onclick="recordSample()">Record 3-Second Sample</button>
<div id="rec-results" style="margin-top:4px"></div>

<h2>6. Screen/System Audio Capture</h2>
<button id="btn-ds" class="secondary" onclick="testDisplayMedia()">Test Screen+Audio Capture</button>
<span id="ds-status" style="font-size:12px;margin-left:8px"></span>

<h2>7. Error Log</h2>
<div id="errors" style="font-size:11px"></div>

<hr style="margin:16px 0;border:none;border-top:1px solid #e0e0e0">
<button onclick="location.reload()" class="secondary">Retry Diagnostic</button>

<script>
// ====== ES5-only — no async/await, no arrow functions, no const/let, no template literals ======

var el = function(id) { return document.getElementById(id); };
var setHtml = function(id, text, cls) {
  var e = el(id);
  if (e) { e.textContent = text; if (cls) e.className = cls; }
};
var logError = function(msg) {
  var d = document.createElement('div');
  d.textContent = '[ERROR] ' + msg;
  d.className = 'fail';
  el('errors').appendChild(d);
};
var logRec = function(msg, cls) {
  var d = document.createElement('div');
  d.textContent = msg;
  d.className = cls || 'info';
  el('rec-results').appendChild(d);
};
var addDevice = function(text) {
  var d = document.createElement('div');
  d.textContent = text;
  d.style.fontSize = '12px';
  el('devices').appendChild(d);
};

// ====== Step 1: Environment (runs immediately, zero async deps) ======
try {
  setHtml('s-js', 'OK (' + new Date().toISOString() + ')', 'pass');
  setHtml('s-ua', navigator.userAgent.substring(0, 120));
  setHtml('s-md', navigator.mediaDevices ? 'AVAILABLE' : 'UNAVAILABLE', navigator.mediaDevices ? 'pass' : 'fail');
  setHtml('s-gum', (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) ? 'AVAILABLE' : 'UNAVAILABLE',
    (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) ? 'pass' : 'fail');
  setHtml('s-gdm', (navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia) ? 'AVAILABLE' : 'UNAVAILABLE',
    (navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia) ? 'pass' : 'fail');
  setHtml('s-mr', (typeof MediaRecorder !== 'undefined') ? 'AVAILABLE' : 'UNAVAILABLE',
    (typeof MediaRecorder !== 'undefined') ? 'pass' : 'fail');
  setHtml('s-ac', (typeof AudioContext !== 'undefined' || typeof webkitAudioContext !== 'undefined') ? 'AVAILABLE' : 'UNAVAILABLE',
    (typeof AudioContext !== 'undefined' || typeof webkitAudioContext !== 'undefined') ? 'pass' : 'fail');
} catch(e) {
  logError('Environment check failed: ' + e.message);
}

// ====== Step 2: Enumerate devices (user-triggered) ======
var enumerateDevices = function() {
  var btn = el('btn-enum');
  btn.disabled = true;
  btn.textContent = 'Enumerating...';
  el('devices').textContent = '';

  if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) {
    addDevice('enumerateDevices UNAVAILABLE');
    btn.disabled = false; btn.textContent = 'Enumerate Devices';
    return;
  }

  navigator.mediaDevices.enumerateDevices().then(function(devices) {
    var counts = {};
    devices.forEach(function(d) { counts[d.kind] = (counts[d.kind]||0) + 1; });
    addDevice('Total devices: ' + devices.length + ' (' +
      Object.keys(counts).map(function(k) { return k + ': ' + counts[k]; }).join(', ') + ')');
    var inputs = devices.filter(function(d) { return d.kind === 'audioinput'; });
    addDevice('Audio inputs found: ' + inputs.length);
    if (inputs.length > 0) {
      inputs.forEach(function(d, i) {
        var label = d.label || '(no label — may need microphone permission)';
        addDevice('  Input ' + i + ': ' + label.substring(0,70) + (d.groupId ? ' [group=' + d.groupId.substring(0,12) + '...]' : ''));
      });
    }
    btn.disabled = false; btn.textContent = 'Refresh Devices';
  }).catch(function(e) {
    addDevice('FAILED: ' + e.message);
    btn.disabled = false; btn.textContent = 'Retry';
  });
};

// ====== Step 3: Microphone (button-triggered, 10s timeout) ======
var micStream = null;

var requestMicrophone = function() {
  var btn = el('btn-mic');
  btn.disabled = true;
  btn.textContent = 'Requesting (10s timeout)...';
  el('mic-status').textContent = '';

  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setHtml('mic-status', 'getUserMedia UNAVAILABLE', 'fail');
    btn.disabled = false; btn.textContent = 'Retry';
    return;
  }

  // Race: getUserMedia vs 10s timeout
  var timedOut = false;
  var timer = setTimeout(function() {
    timedOut = true;
    setHtml('mic-status', 'TIMEOUT: Permission dialog may not appear in Zoom webview', 'fail');
    btn.disabled = false; btn.textContent = 'Retry Microphone Access';
  }, 10000);

  navigator.mediaDevices.getUserMedia({audio: true}).then(function(stream) {
    if (timedOut) { stream.getTracks().forEach(function(t) { t.stop(); }); return; }
    clearTimeout(timer);
    micStream = stream;
    var tracks = stream.getAudioTracks();
    setHtml('mic-status', 'GRANTED — ' + tracks.length + ' audio track(s)', 'pass');
    if (tracks.length > 0) {
      var s = tracks[0].getSettings();
      setHtml('mic-status', 'GRANTED — ' + s.sampleRate + 'Hz, ' + s.channelCount + 'ch, label: ' + tracks[0].label.substring(0,40), 'pass');
      el('btn-rec').disabled = false;
    }
    btn.textContent = 'Microphone Active';
  }).catch(function(e) {
    if (timedOut) return;
    clearTimeout(timer);
    setHtml('mic-status', 'FAILED: ' + (e.name||'Error') + ' — ' + e.message, 'fail');
    if (e.name === 'NotAllowedError') setHtml('mic-status', 'BLOCKED: Permission denied or webview blocked prompt', 'fail');
    btn.disabled = false; btn.textContent = 'Retry Microphone Access';
  });
};

// ====== Step 4: Record sample (button-triggered, after mic obtained) ======
var recordSample = function() {
  if (!micStream) return;
  var btn = el('btn-rec');
  btn.disabled = true;
  btn.textContent = 'Recording...';
  el('rec-results').textContent = '';

  var AudioCtx = window.AudioContext || window.webkitAudioContext;
  var chunks = [];
  var mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : undefined;
  var rec;

  try {
    rec = new MediaRecorder(micStream, mime ? {mimeType: mime} : undefined);
  } catch(e) {
    logRec('MediaRecorder failed: ' + e.message, 'fail');
    btn.disabled = false; btn.textContent = 'Record 3-Second Sample';
    return;
  }

  rec.ondataavailable = function(e) { if (e.data.size > 0) chunks.push(e.data); };

  var stopped = false;
  var timer = setTimeout(function() {
    if (!stopped) { try { rec.stop(); } catch(e) {} }
  }, 3000);

  rec.onstop = function() {
    stopped = true;
    clearTimeout(timer);
    var blob = new Blob(chunks);
    logRec('Sample: ' + blob.size + ' bytes, MIME: ' + (rec.mimeType||'default'));
    if (blob.size > 200) { logRec('AUDIO DATA DETECTED', 'pass'); }
    else { logRec('Negligible data (silence or no input)', 'fail'); }

    // Analyze with AudioContext
    if (AudioCtx) {
      try {
        var ctx = new AudioCtx();
        var reader = new FileReader();
        reader.onload = function() {
          ctx.decodeAudioData(reader.result).then(function(buf) {
            var peak = 0, rms = 0, n = 0;
            for (var c = 0; c < buf.numberOfChannels; c++) {
              var data = buf.getChannelData(c);
              for (var i = 0; i < data.length; i++) { peak = Math.max(peak, Math.abs(data[i])); rms += data[i]*data[i]; n++; }
            }
            rms = Math.sqrt(rms / Math.max(1, n));
            logRec('Peak: ' + (peak*100).toFixed(1) + '%, RMS: ' + (rms*100).toFixed(1) + '%');
            logRec('Duration: ' + buf.duration.toFixed(2) + 's, Channels: ' + buf.numberOfChannels);
            if (rms > 0.005) {
              logRec('SIGNAL DETECTED (RMS ' + (rms*100).toFixed(1) + '%)', 'pass');
              logRec('  To verify source: mute yourself in Zoom. If signal vanishes -> MICROPHONE ONLY.', 'info');
              logRec('  If signal persists while muted and others speak -> REMOTE AUDIO ACCESSIBLE.', 'pass');
            } else {
              logRec('SILENCE — no meaningful signal', 'fail');
            }
            ctx.close();
            btn.disabled = false; btn.textContent = 'Record Again';
          }).catch(function(e) {
            logRec('AudioContext decode failed: ' + e.message, 'fail');
            ctx.close();
            btn.disabled = false; btn.textContent = 'Record Again';
          });
        };
        reader.onerror = function() { logRec('FileReader failed', 'fail'); btn.disabled = false; btn.textContent = 'Record Again'; };
        reader.readAsArrayBuffer(blob);
      } catch(e) {
        logRec('AudioContext setup failed: ' + e.message, 'fail');
        btn.disabled = false; btn.textContent = 'Record Again';
      }
    } else {
      btn.disabled = false; btn.textContent = 'Record Again';
    }
  };

  rec.onerror = function(e) {
    clearTimeout(timer);
    logRec('Recorder error: ' + (e.error ? e.error.message : 'unknown'), 'fail');
    btn.disabled = false; btn.textContent = 'Retry';
  };

  rec.start(1000);
  logRec('Recording 3 seconds...');

  // Timeout guard
  setTimeout(function() {
    if (!stopped) { logRec('Recorder stalled', 'fail'); btn.disabled = false; btn.textContent = 'Retry'; }
  }, 6000);
};

// ====== Step 5: getDisplayMedia (button-triggered, 15s timeout) ======
var testDisplayMedia = function() {
  var btn = el('btn-ds');
  btn.disabled = true;
  btn.textContent = 'Requesting (15s timeout)...';
  el('ds-status').textContent = '';

  if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
    setHtml('ds-status', 'getDisplayMedia UNAVAILABLE', 'fail');
    btn.disabled = false; btn.textContent = 'Test Screen+Audio Capture';
    return;
  }

  var timedOut = false;
  var timer = setTimeout(function() {
    timedOut = true;
    setHtml('ds-status', 'TIMEOUT — picker may not appear in Zoom webview', 'fail');
    btn.disabled = false; btn.textContent = 'Retry';
  }, 15000);

  navigator.mediaDevices.getDisplayMedia({video: true, audio: true}).then(function(stream) {
    if (timedOut) { stream.getTracks().forEach(function(t) { t.stop(); }); return; }
    clearTimeout(timer);
    var at = stream.getAudioTracks();
    var vt = stream.getVideoTracks();
    setHtml('ds-status', 'GRANTED — ' + vt.length + ' video, ' + at.length + ' audio track(s)', 'pass');
    if (at.length > 0) {
      setHtml('ds-status', 'AUDIO TRACK FOUND: ' + at.length + ' track(s) — system/meeting audio MAY be accessible', 'pass');
    } else {
      setHtml('ds-status', 'NO AUDIO TRACK — getDisplayMedia does not expose system/meeting audio', 'fail');
      logError('REMOTE AUDIO: getDisplayMedia returned video but NO audio track. Audio capture not available.');
    }
    stream.getTracks().forEach(function(t) { t.stop(); });
    btn.disabled = false; btn.textContent = 'Test Again';
  }).catch(function(e) {
    if (timedOut) return;
    clearTimeout(timer);
    setHtml('ds-status', 'FAILED: ' + (e.name||'Error') + ' — ' + e.message, 'fail');
    btn.disabled = false; btn.textContent = 'Retry';
  });
};
</script>
</body>
</html>"""


@router.api_route("/audio-test", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def audio_test():
    return HTMLResponse(
        _AUDIO_TEST_HTML,
        headers={
            # Override global CSP to permit the inline diagnostic script.
            # Only affects /audio-test — the main app CSP is unchanged.
            "Content-Security-Policy": (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; "
                "base-uri 'none'; "
                "form-action 'none'"
            ),
        },
    )
