/**
 * Getting the "before" side.
 *
 * A round-trip check is only as good as its input, and the input is the HTML
 * SuperDocs put on the wire -- not the HTML that came back out of the editor,
 * and not something re-fetched later. This reads the shapes that HTML actually
 * arrives in: a saved SSE stream, one event as JSON, an array of events, or a
 * chat/save response body.
 */

const HTML_FIELDS = ['content', 'document_html', 'updated_html', 'html', 'prepared_html'];

/**
 * @param {string} payload raw text: SSE stream, JSON object, or JSON array
 * @param {{ documentId?: string, event?: string }} [options]
 * @returns {{ html: string, source: string, documentId: string|null, candidates: number }}
 */
export function extractDocumentHtml(payload, options = {}) {
  const wanted = options.event || 'document_sync';
  const text = String(payload);

  const events = text.trimStart().startsWith('{') || text.trimStart().startsWith('[')
    ? readJsonPayload(text)
    : readSseStream(text, wanted);

  const matching = events.filter((event) => {
    if (options.documentId && event.documentId && event.documentId !== options.documentId) return false;
    // An untyped payload is a plain response body, so its HTML is the one on offer.
    // A typed one is an event, and only the event that was asked for counts:
    // `final` carries HTML too, and it is the after side, not the before side.
    return event.type ? event.type === wanted : true;
  });

  const usable = matching.filter((event) => event.html);
  if (usable.length === 0) {
    const seen = [...new Set(events.map((event) => event.type).filter(Boolean))];
    throw new Error(
      `no ${wanted} HTML found in the payload. Expected an SSE stream containing `
      + `"event: ${wanted}", or JSON carrying one of: ${HTML_FIELDS.join(', ')}.`
      + (seen.length > 0 ? ` The payload does carry: ${seen.join(', ')} -- pass --event to read one of those.` : ''),
    );
  }

  // The last one wins: a stream carries the newest prepared HTML at the end.
  const chosen = usable[usable.length - 1];
  return {
    html: chosen.html,
    source: chosen.type || 'json',
    documentId: chosen.documentId || null,
    candidates: usable.length,
  };
}

function readSseStream(text, wanted) {
  const events = [];
  let currentEvent = null;
  const dataLines = [];

  const flush = () => {
    if (dataLines.length === 0) {
      currentEvent = null;
      return;
    }
    const data = dataLines.join('\n');
    dataLines.length = 0;
    let parsed;
    try {
      parsed = JSON.parse(data);
    } catch {
      currentEvent = null;
      return;
    }
    events.push(toEvent(parsed, currentEvent || parsed.type));
    currentEvent = null;
  };

  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trimEnd();
    if (line === '') {
      flush();
      continue;
    }
    if (line.startsWith('event:')) {
      currentEvent = line.slice(6).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''));
      continue;
    }
    if (line.startsWith(':')) continue; // comment / keep-alive
  }
  flush();

  return events.filter((event) => !wanted || !event.type || event.type === wanted || event.html);
}

function readJsonPayload(text) {
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    throw new Error(`payload is neither an SSE stream nor valid JSON: ${error.message}`);
  }
  const list = Array.isArray(parsed) ? parsed : [parsed];
  return list.map((entry) => toEvent(entry, entry && entry.type));
}

function toEvent(parsed, type) {
  const raw = parsed && typeof parsed === 'object' ? parsed : {};
  let html = '';
  for (const field of HTML_FIELDS) {
    if (typeof raw[field] === 'string' && raw[field].length > 0) {
      html = raw[field];
      break;
    }
  }
  // Multi-document responses nest per-document HTML under `documents`.
  if (!html && raw.documents && typeof raw.documents === 'object') {
    const first = Object.values(raw.documents).find(
      (entry) => entry && typeof entry === 'object' && HTML_FIELDS.some((field) => typeof entry[field] === 'string'),
    );
    if (first) {
      const field = HTML_FIELDS.find((name) => typeof first[name] === 'string');
      html = first[field];
    }
  }
  return {
    type: type || raw.type || null,
    html,
    documentId: raw.focused_document_id || raw.document_id || null,
    raw,
  };
}

export { HTML_FIELDS };
