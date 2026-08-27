import { randomUUID } from 'node:crypto';
import { createServer } from 'node:http';
import { once } from 'node:events';
import { chmod, mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';

const SAFE_RESPONSE_HEADERS = new Set([
  'content-type', 'retry-after', 'x-usage-limit', 'x-usage-used', 'x-usage-remaining',
]);
const SECRET_PATTERN = /(?:bearer\s+[a-z0-9._~+/=-]+|x-amz-(?:signature|credential|security-token)|superdocs[_-]?api[_-]?key|api[_-]?key["'=:\s]+[a-z0-9._~+/=-]{8,})/i;
const SIGNED_QUERY_PATTERN = /[?&](?:x-amz-|signature=|token=|sig=)/i;

export function assertRecordingAuthorized(environment = process.env) {
  if (environment.SDX_RECORD_FIXTURE !== '1') {
    throw new Error('Live fixture recording requires the explicit SDX_RECORD_FIXTURE=1 flag.');
  }
  if (!environment.SUPERDOCS_API_KEY) {
    throw new Error('Live fixture recording requires SUPERDOCS_API_KEY in the environment.');
  }
}

function safeHeaders(headers) {
  const output = {};
  for (const [name, value] of new Headers(headers).entries()) {
    if (SAFE_RESPONSE_HEADERS.has(name.toLowerCase())) output[name.toLowerCase()] = value;
  }
  return output;
}

function sanitizer() {
  const maps = new Map();
  const next = (kind, value) => {
    const key = `${kind}:${value}`;
    if (!maps.has(key)) {
      const count = [...maps.keys()].filter((entry) => entry.startsWith(`${kind}:`)).length + 1;
      maps.set(key, `<${kind}-${count}>`);
    }
    return maps.get(key);
  };
  const visit = (value, key = '') => {
    if (Array.isArray(value)) return value.map((entry) => visit(entry, key));
    if (value && typeof value === 'object') {
      const output = {};
      for (const [childKey, childValue] of Object.entries(value)) {
        if (/authorization|cookie|api[_-]?key|secret/i.test(childKey)) continue;
        output[childKey] = visit(childValue, childKey);
      }
      return output;
    }
    if (typeof value === 'number' && /usage|used|remaining|limit/i.test(key)) return 0;
    if (typeof value !== 'string') return value;
    if (key === 'curl_example') return '<omitted-command>';
    if (SIGNED_QUERY_PATTERN.test(value)) return '<signed-url>';
    if (/url$/i.test(key)) return '<signed-url>';
    if (/^(?:created_at|updated_at|expires_at|timestamp)$/i.test(key)) return '<timestamp>';
    if (/^(?:job_id)$/i.test(key)) return next('job', value);
    if (/^(?:session_id)$/i.test(key)) return next('session', value);
    if (/^(?:document_id|durable_document_id)$/i.test(key)) return next('document', value);
    if (/^(?:upload_id)$/i.test(key)) return next('upload', value);
    if (/^(?:version_id)$/i.test(key)) return next('version', value);
    if (/^(?:request_id)$/i.test(key)) return next('request', value);
    if (/^(?:change_id)$/i.test(key)) return next('change', value);
    if (/^(?:chunk_id)$/i.test(key)) return next('chunk', value);
    if (/^(?:message|old_html|new_html|updated_html|response)$/i.test(key) && value.length > 0) return `<synthetic-${key.replaceAll('_', '-')}>`;
    return value;
  };
  return visit;
}

export function validateCassetteSafe(cassette) {
  if (!cassette || cassette.schemaVersion !== 1 || !Array.isArray(cassette.interactions)) {
    throw new Error('Cassette schema is invalid.');
  }
  const serialized = JSON.stringify(cassette);
  if (SECRET_PATTERN.test(serialized) || SIGNED_QUERY_PATTERN.test(serialized)) {
    throw new Error('Cassette validation rejected a credential or signed query.');
  }
  for (const interaction of cassette.interactions) {
    if (!['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].includes(interaction.request?.method)) throw new Error('Cassette request method is invalid.');
    if (typeof interaction.request?.path !== 'string' || !interaction.request.path.startsWith('/') || interaction.request.path.includes('?')) {
      throw new Error('Cassette request path must be query-free.');
    }
    if (JSON.stringify(interaction).length > 512_000) throw new Error('Cassette interaction exceeds the safe size limit.');
  }
  return cassette;
}

export class SanitizedCassetteRecorder {
  #interactions = [];
  #sanitize = sanitizer();
  #billableEdits = 0;
  #pathIds = new Map();

  constructor({ provenance = 'live-recorded disposable synthetic document' } = {}) {
    this.provenance = provenance;
  }

  #safePath(path) {
    const replace = (kind, value) => {
      const key = `${kind}:${value}`;
      if (!this.#pathIds.has(key)) {
        const count = [...this.#pathIds.keys()].filter((entry) => entry.startsWith(`${kind}:`)).length + 1;
        this.#pathIds.set(key, `<${kind}-${count}>`);
      }
      return this.#pathIds.get(key);
    };
    return path
      .replace(/(\/v1\/jobs\/)([^/]+)/, (_match, prefix, id) => `${prefix}${replace('job', id)}`)
      .replace(/(\/v1\/chat\/)([^/]+)(\/(?:approve|continue))/, (_match, prefix, id, suffix) => `${prefix}${replace('session', id)}${suffix}`)
      .replace(/(\/v1\/uploads\/)([^/]+)(\/process)/, (_match, prefix, id, suffix) => `${prefix}${replace('upload', id)}${suffix}`);
  }

  async capture({ method, url, requestBody, response }) {
    const parsedUrl = new URL(url);
    if (method === 'POST' && parsedUrl.pathname === '/v1/chat/async') {
      this.#billableEdits += 1;
      if (this.#billableEdits > 1) throw new Error('Recording cap exceeded: at most one potentially billable edit is permitted.');
    }
    const responseText = await response.clone().text();
    let responseBody = null;
    if (responseText) {
      try { responseBody = JSON.parse(responseText); }
      catch { responseBody = responseText.slice(0, 4096); }
    }
    this.#interactions.push({
      request: {
        method,
        path: this.#safePath(parsedUrl.pathname),
        body: requestBody === undefined ? null : this.#sanitize(requestBody),
      },
      response: {
        status: response.status,
        headers: safeHeaders(response.headers),
        body: this.#sanitize(responseBody),
      },
    });
  }

  cassette() {
    return validateCassetteSafe({
      schemaVersion: 1,
      provenance: this.provenance,
      constraints: { potentiallyBillableEditCap: 1, signedStorageRecorded: false, rawDocumentBytesRecorded: false },
      interactions: this.#interactions,
    });
  }

  async write(path) {
    const cassette = this.cassette();
    await mkdir(dirname(path), { recursive: true, mode: 0o700 });
    const temporary = `${path}.${process.pid}.${randomUUID()}.tmp`;
    await writeFile(temporary, `${JSON.stringify(cassette, null, 2)}\n`, { mode: 0o600, flag: 'wx' });
    await chmod(temporary, 0o600); await rename(temporary, path); await chmod(path, 0o600);
  }
}

export function createRecordingFetch({ apiBaseUrl, recorder, realFetch = fetch }) {
  const api = new URL(apiBaseUrl);
  return async (input, init = {}) => {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
    const method = (init.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();
    let requestBody;
    if (url.origin === api.origin && url.pathname.startsWith(api.pathname)) {
      if (typeof init.body === 'string' && init.body.length > 0) requestBody = JSON.parse(init.body);
      else if (init.body !== undefined && init.body !== null) throw new Error('Recorder refuses non-JSON API request bodies.');
    }
    const response = await realFetch(input, init);
    if (url.origin === api.origin && url.pathname.startsWith(api.pathname)) {
      await recorder.capture({ method, url, requestBody, response });
    }
    return response;
  };
}

export async function readCassette(path) {
  return validateCassetteSafe(JSON.parse(await readFile(path, 'utf8')));
}

export async function startReplayServer(cassetteInput) {
  const cassette = validateCassetteSafe(cassetteInput); let index = 0;
  const server = createServer(async (request, response) => {
    const interaction = cassette.interactions[index];
    if (!interaction) { response.writeHead(409); response.end('Replay exhausted'); return; }
    const url = new URL(request.url ?? '/', 'http://127.0.0.1');
    const decodedPath = decodeURIComponent(url.pathname);
    if (request.method !== interaction.request.method || decodedPath !== interaction.request.path) {
      response.writeHead(409); response.end('Replay request mismatch'); return;
    }
    index += 1;
    response.writeHead(interaction.response.status, interaction.response.headers);
    response.end(interaction.response.body === null ? '' : typeof interaction.response.body === 'string' ? interaction.response.body : JSON.stringify(interaction.response.body));
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); if (!address || typeof address === 'string') throw new Error('Replay server failed to bind.');
  return {
    baseUrl: `http://127.0.0.1:${address.port}`,
    consumed: () => index,
    close: async () => { server.close(); await once(server, 'close'); },
  };
}
