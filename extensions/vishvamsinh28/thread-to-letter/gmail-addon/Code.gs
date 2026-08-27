/**
 * Thread to letter — Gmail add-on.
 *
 * Reads the open thread, asks SuperDocs which commitments are actually in it, shows them
 * for review, and attaches the resulting letter to a draft reply through Gmail's own API.
 *
 * ---------------------------------------------------------------------------
 * STATUS: written, not verified against live Gmail. See ../README.md.
 *
 * The pipeline this calls — thread parsing, the extraction prompt, quote verification,
 * the superseded-without-replacement check — is the same logic as the Python package,
 * and that half is exercised against the live SuperDocs API and covered by tests. What
 * has not been exercised is this file: the CardService rendering and the Gmail read and
 * draft-write calls. Treat it as a reference implementation to sideload, not as a
 * shipped feature.
 * ---------------------------------------------------------------------------
 *
 * Setup: Extensions -> Apps Script, paste these files in, then
 * Project Settings -> Script Properties -> add SUPERDOCS_API_KEY.
 * Deploy -> Test deployments -> Install.
 */

var API_BASE = 'https://api.superdocs.app';

/** The key lives in Script Properties, never in this file. */
function apiKey_() {
  var key = PropertiesService.getScriptProperties().getProperty('SUPERDOCS_API_KEY');
  if (!key) {
    throw new Error(
      'No SUPERDOCS_API_KEY. Project Settings -> Script Properties -> add it. ' +
      'Get a key from use.superdocs.app -> Settings -> API Keys.');
  }
  return key;
}

// --- Gmail side -------------------------------------------------------------

/** Read the open thread into the same shape the Python package uses. */
function readThread_(messageId) {
  var thread = GmailApp.getMessageById(messageId).getThread();
  return thread.getMessages().map(function (m, i) {
    return {
      index: i + 1,
      sender: m.getFrom(),
      date: m.getDate().toUTCString(),
      subject: m.getSubject(),
      body: stripQuoted_(m.getPlainBody())
    };
  });
}

/** Drop quoted history and signatures, so each message is only what its sender typed. */
function stripQuoted_(body) {
  var kept = [];
  var lines = (body || '').split('\n');
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i];
    if (/^\s*>+/.test(line)) continue;
    if (/^\s*On .{0,80}wrote:\s*$/.test(line)) continue;
    if (/^--\s*$/.test(line)) break;
    kept.push(line);
  }
  return kept.join('\n').trim();
}

function renderThread_(messages) {
  return messages.map(function (m) {
    return '--- message ' + m.index + ' ---\n' +
      'From: ' + m.sender + '\nDate: ' + m.date + '\n\n' + m.body;
  }).join('\n\n');
}

// --- SuperDocs side ---------------------------------------------------------

function chat_(sessionId, message) {
  var response = UrlFetchApp.fetch(API_BASE + '/v1/chat', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + apiKey_() },
    payload: JSON.stringify({
      message: message, session_id: sessionId, approval_mode: 'approve_all'
    }),
    muteHttpExceptions: true
  });
  var code = response.getResponseCode();
  if (code >= 400) {
    throw new Error('SuperDocs returned ' + code + ': ' + response.getContentText().slice(0, 300));
  }
  var body = JSON.parse(response.getContentText());
  return (body.document_changes && body.document_changes.updated_html) || '';
}

function exportDocument_(sessionId, format, filename) {
  var response = UrlFetchApp.fetch(API_BASE + '/v1/documents/export', {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + apiKey_() },
    payload: JSON.stringify({
      session_id: sessionId, format: format, options: { filename: filename }
    }),
    muteHttpExceptions: true
  });
  if (response.getResponseCode() >= 400) {
    throw new Error('Export failed: ' + response.getContentText().slice(0, 300));
  }
  return response.getBlob().setName(filename + (format === 'docx' ? '.docx' : '.' + format));
}

// --- the pipeline -----------------------------------------------------------

function extractCommitments_(sessionId, messages) {
  var html = chat_(sessionId, EXTRACT_PROMPT.replace('{thread}', renderThread_(messages)));
  var rows = parseTable_(html);
  return verifyQuotes_(rows, messages);
}

/**
 * Every claimed quote must really appear in the thread. A row that fails is kept and
 * shown as unverified rather than dropped — "the model claimed this and could not back
 * it up" is exactly what a reviewer wants to see.
 */
function verifyQuotes_(rows, messages) {
  var perMessage = messages.map(function (m) { return normalise_(m.body); });
  rows.forEach(function (row) {
    var fragments = String(row.quote || '').split(/\s*(?:\.\.\.|…)\s*/)
      .map(normalise_).filter(function (f) { return f.length > 0; });
    var total = fragments.reduce(function (n, f) { return n + f.length; }, 0);
    row.quoteFound = false;
    row.locatedIn = null;
    if (!fragments.length || total < 12) {
      row.quoteNote = 'the quote is too short to identify anything';
      return;
    }
    for (var i = 0; i < perMessage.length; i++) {
      if (containsInOrder_(perMessage[i], fragments)) {
        row.quoteFound = true;
        row.locatedIn = i + 1;
        row.quoteNote = '';
        return;
      }
    }
    row.quoteNote = 'these words do not appear in the thread';
  });
  return rows;
}

function containsInOrder_(haystack, fragments) {
  var cursor = 0;
  for (var i = 0; i < fragments.length; i++) {
    var at = haystack.indexOf(fragments[i], cursor);
    if (at === -1) return false;
    cursor = at + fragments[i].length;
  }
  return true;
}

function normalise_(text) {
  return String(text || '')
    .replace(/[‘’]/g, "'").replace(/[“”]/g, '"')
    .replace(/[–—]/g, '-').replace(/\s+/g, ' ').trim();
}

/** Pull the first table out of the generated document. */
function parseTable_(html) {
  var rows = [];
  var tableMatch = /<table[^>]*>([\s\S]*?)<\/table>/i.exec(html || '');
  if (!tableMatch) return rows;
  var trs = tableMatch[1].match(/<tr[^>]*>[\s\S]*?<\/tr>/gi) || [];
  var header = null;
  trs.forEach(function (tr) {
    var cells = (tr.match(/<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi) || []).map(function (c) {
      return normalise_(c.replace(/<[^>]+>/g, ' '));
    });
    if (!cells.length) return;
    if (!header) { header = cells.map(function (c) { return c.toLowerCase(); }); return; }
    rows.push({
      party: cells[0] || '', owesTo: cells[1] || '', obligation: cells[2] || '',
      due: cells[3] || '', status: normaliseStatus_(cells[4]), source: cells[5] || '',
      quote: cells[6] || ''
    });
  });
  return rows;
}

/** Anything unrecognised is NOT firm. Guessing firm turns an intention into a promise. */
function normaliseStatus_(raw) {
  var text = String(raw || '').toLowerCase();
  if (text.indexOf('firm') !== -1) return 'firm';
  if (text.indexOf('supersed') !== -1 || text.indexOf('revised') !== -1) return 'superseded';
  if (text.indexOf('hedge') !== -1 || text.indexOf('tentative') !== -1) return 'hedged';
  if (text.indexOf('second') !== -1) return 'second-hand';
  return 'proposed';
}

/** A superseded commitment with no replacement means the letter is missing the live one. */
function danglingSuperseded_(rows) {
  var firmParties = {};
  rows.forEach(function (r) {
    if (r.status === 'firm') firmParties[partyKey_(r.party)] = true;
  });
  return rows.filter(function (r) {
    return r.status === 'superseded' && !firmParties[partyKey_(r.party)];
  });
}

function partyKey_(party) {
  return normalise_(party).toLowerCase().replace(/&/g, 'and');
}

// --- cards ------------------------------------------------------------------

function onGmailMessageOpen(event) {
  var messageId = event.gmail.messageId;
  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('Thread to letter'))
    .addSection(CardService.newCardSection()
      .addWidget(CardService.newTextParagraph().setText(
        'Read this thread and pull out what people actually committed to — not a ' +
        'polite summary. You review each one before anything is written.'))
      .addWidget(CardService.newTextButton()
        .setText('Find commitments')
        .setOnClickAction(CardService.newAction()
          .setFunctionName('onFindCommitments')
          .setParameters({ messageId: messageId }))))
    .build();
}

function onFindCommitments(event) {
  var messageId = event.parameters.messageId;
  var messages = readThread_(messageId);
  var sessionId = 'gmail-' + GmailApp.getMessageById(messageId).getThread().getId();
  var rows = extractCommitments_(sessionId, messages);

  var section = CardService.newCardSection();
  if (!rows.length) {
    section.addWidget(CardService.newTextParagraph().setText(
      '<b>No commitments were made in this thread.</b><br>' +
      'That is a real answer. The letter will say exactly that.'));
  } else {
    var group = CardService.newSelectionInput()
      .setType(CardService.SelectionInputType.CHECK_BOX)
      .setFieldName('chosen');
    rows.forEach(function (row, i) {
      var label = row.status.toUpperCase() + ' · ' + row.party + ': ' +
        row.obligation + (row.due ? ' (by ' + row.due + ')' : '') +
        (row.quoteFound ? '' : '  [UNVERIFIED: ' + row.quoteNote + ']');
      group.addItem(label, String(i), row.status === 'firm' && row.quoteFound);
    });
    section.addWidget(group);

    var dangling = danglingSuperseded_(rows);
    if (dangling.length) {
      section.addWidget(CardService.newTextParagraph().setText(
        '<b>Warning:</b> a commitment was replaced but the replacement is not in this ' +
        'list. The letter would be missing the obligation that actually stands.'));
    }
  }

  section.addWidget(CardService.newTextButton()
    .setText('Write letter and attach to reply')
    .setOnClickAction(CardService.newAction()
      .setFunctionName('onWriteLetter')
      .setParameters({ messageId: messageId, rows: JSON.stringify(rows) })));

  return CardService.newCardBuilder()
    .setHeader(CardService.newCardHeader().setTitle('What was committed to'))
    .addSection(section).build();
}

function onWriteLetter(event) {
  var messageId = event.parameters.messageId;
  var rows = JSON.parse(event.parameters.rows);
  var picked = ((event.formInput && event.formInput.chosen) || [])
    .map(function (i) { return rows[parseInt(i, 10)]; })
    .filter(Boolean);

  var message = GmailApp.getMessageById(messageId);
  var sessionId = 'gmail-' + message.getThread().getId();
  var listed = picked.map(function (r, i) {
    return (i + 1) + '. ' + r.party + ' will ' + r.obligation +
      (r.due ? ', due ' + r.due : ', no date was given') +
      '. Owed to ' + (r.owesTo || 'the other party') +
      '. Recorded because they wrote: "' + r.quote + '"';
  }).join('\n');

  var prompt = picked.length
    ? LETTER_PROMPT.replace('{commitments}', listed).replace('{subject}', message.getSubject())
    : NOTHING_PROMPT.replace('{subject}', message.getSubject());
  chat_(sessionId, prompt);

  var blob = exportDocument_(sessionId, 'docx', slug_(message.getSubject()));
  message.createDraftReply(replyBody_(picked, blob.getName()), { attachments: [blob] });

  return CardService.newActionResponseBuilder()
    .setNotification(CardService.newNotification().setText(
      picked.length
        ? 'Draft reply created with ' + picked.length + ' commitment(s) attached.'
        : 'Draft reply created: nothing was committed to in this thread.'))
    .build();
}

function replyBody_(picked, filename) {
  if (!picked.length) {
    return 'I have put our discussion on record. Reading it back, I could not find ' +
      'anything either of us actually committed to, so the attached says exactly that.\n\n' +
      'If you believe something was agreed, tell me and I will correct it.\n\n' +
      'Attached: ' + filename + '\n';
  }
  var lines = picked.map(function (r) {
    return '  - ' + r.party + ': ' + r.obligation + (r.due ? ' by ' + r.due : '');
  });
  return 'I have put what we agreed into the attached, so we are working from the same ' +
    'record.\n\nIt states only what was actually committed to in this thread:\n\n' +
    lines.join('\n') + '\n\nAnything discussed but not agreed has been left out on ' +
    'purpose. If I have recorded any of it wrongly, tell me and I will correct it.\n\n' +
    'Attached: ' + filename + '\n';
}

function slug_(text) {
  return String(text || 'letter').toLowerCase().replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '').slice(0, 60) || 'letter';
}
