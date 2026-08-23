/* popup.js — LatBuild browser extension */

const DEFAULT_PORT = 5001;

function getPort() {
  const input = document.getElementById('port-input');
  return parseInt(input?.value || DEFAULT_PORT, 10);
}

function getServiceUrl() {
  return `http://localhost:${getPort()}`;
}

async function checkService() {
  const statusEl = document.getElementById('status-msg');
  const port = getPort();
  try {
    const resp = await fetch(`http://localhost:${port}/api/sections`, {
      signal: AbortSignal.timeout(2000),
    });
    if (resp.ok || resp.status === 400) {
      // 400 = "No PDF uploaded" — service is running
      statusEl.textContent = `✓ Service running on port ${port}`;
      statusEl.className = 'status running';
    } else {
      statusEl.textContent = `Service responded with status ${resp.status}`;
      statusEl.className = 'status';
    }
  } catch (err) {
    statusEl.textContent = `Service not reachable on port ${port}. Run: python app.py`;
    statusEl.className = 'status error';
  }
}

document.getElementById('open-btn')?.addEventListener('click', (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: getServiceUrl() });
});

document.getElementById('check-btn')?.addEventListener('click', checkService);

// Restore saved port
chrome.storage?.local.get(['port'], (result) => {
  if (result.port) {
    const input = document.getElementById('port-input');
    if (input) input.value = result.port;
  }
});

document.getElementById('port-input')?.addEventListener('change', (e) => {
  chrome.storage?.local.set({ port: e.target.value });
});

// Auto-check on open
checkService();
