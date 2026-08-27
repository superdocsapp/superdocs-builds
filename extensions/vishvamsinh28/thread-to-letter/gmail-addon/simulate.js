/**
 * Run the add-on's real code outside Google.
 *
 * Apps Script is ordinary JavaScript against a handful of Google globals. Stub those
 * globals and Code.gs runs anywhere — same file, unmodified, calling the same live
 * SuperDocs API. What that leaves unproven is only Google's own binding: whether their
 * runtime renders the cards this builds and delivers the events it expects.
 *
 * So this is not a mock of the add-on. It IS the add-on, with Gmail replaced by an .mbox
 * and CardService replaced by something that prints.
 *
 *   node simulate.js ../threads/migration-project.mbox
 *
 * Costs two operations. Reads SUPERDOCS_API_KEY from ../.env or the environment.
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

// --- the thread, standing in for Gmail --------------------------------------

function parseMbox(text) {
  return text.split(/^From \S+.*$/m).map(s => s.trim()).filter(Boolean).map((chunk, i) => {
    const split = chunk.indexOf('\n\n');
    const headerText = chunk.slice(0, split);
    const headers = {};
    headerText.split('\n').forEach(line => {
      const m = /^([A-Za-z-]+):\s*(.*)$/.exec(line);
      if (m) headers[m[1].toLowerCase()] = m[2];
    });
    return {
      index: i + 1,
      from: headers.from || '',
      subject: headers.subject || '',
      date: new Date(headers.date || Date.now()),
      body: chunk.slice(split + 2),
      id: headers['message-id'] || ''
    };
  });
}

const threadPath = process.argv[2] || path.join(__dirname, '..', 'threads', 'migration-project.mbox');
const MESSAGES = parseMbox(fs.readFileSync(threadPath, 'utf8'));
const DRAFTS = [];

// --- Google's globals, stubbed ----------------------------------------------

function gmailMessage(m) {
  return {
    getFrom: () => m.from,
    getSubject: () => m.subject,
    getDate: () => m.date,
    getPlainBody: () => m.body,
    getThread: () => ({
      getId: () => 'simulated-thread',
      getMessages: () => MESSAGES.map(gmailMessage)
    }),
    createDraftReply: (body, options) => {
      DRAFTS.push({ body, attachments: (options && options.attachments) || [] });
      return { getId: () => 'draft-1' };
    }
  };
}

global.GmailApp = {
  getMessageById: id => gmailMessage(MESSAGES[Number(id) - 1] || MESSAGES[0])
};

global.PropertiesService = {
  getScriptProperties: () => ({ getProperty: name => process.env[name] || null })
};

/** Synchronous HTTP, because UrlFetchApp is synchronous and Code.gs relies on that. */
global.UrlFetchApp = {
  fetch: (url, params) => {
    const args = ['-sS', '-X', params.method.toUpperCase(), url,
      '-H', 'Content-Type: ' + (params.contentType || 'application/json'),
      '-w', '\n%{http_code}'];
    Object.entries(params.headers || {}).forEach(([k, v]) => args.push('-H', `${k}: ${v}`));
    if (params.payload) args.push('--data-binary', params.payload);
    const started = Date.now();
    const raw = execFileSync('curl', args, { maxBuffer: 64 * 1024 * 1024 }).toString();
    const cut = raw.lastIndexOf('\n');
    const body = raw.slice(0, cut);
    const code = parseInt(raw.slice(cut + 1), 10);
    CALLS.push({ method: params.method.toUpperCase(), url, code, ms: Date.now() - started });
    return {
      getResponseCode: () => code,
      getContentText: () => body,
      getBlob: () => ({
        _bytes: Buffer.from(body, 'binary'),
        setName(n) { this._name = n; return this; },
        getName() { return this._name; }
      })
    };
  }
};

const CALLS = [];

/** CardService, recording what would have been rendered. */
const widget = kind => (props = {}) => {
  const w = { kind, ...props };
  const chain = name => (...args) => { w[name] = args.length > 1 ? args : args[0]; return w; };
  ['setText', 'setTitle', 'setOnClickAction', 'setFunctionName', 'setParameters',
   'setType', 'setFieldName', 'setNotification'].forEach(n => { w[n] = chain(n); });
  w.addItem = (label, value, selected) => {
    (w.items = w.items || []).push({ label, value, selected });
    return w;
  };
  return w;
};

global.CardService = {
  SelectionInputType: { CHECK_BOX: 'CHECK_BOX' },
  newCardBuilder: () => {
    const card = { sections: [] };
    return {
      setHeader(h) { card.header = h; return this; },
      addSection(s) { card.sections.push(s); return this; },
      build: () => card
    };
  },
  newCardHeader: widget('header'),
  newCardSection: () => {
    const section = { widgets: [] };
    section.addWidget = w => { section.widgets.push(w); return section; };
    return section;
  },
  newTextParagraph: widget('paragraph'),
  newTextButton: widget('button'),
  newSelectionInput: widget('selection'),
  newAction: widget('action'),
  newNotification: widget('notification'),
  newActionResponseBuilder: () => {
    const response = {};
    return {
      setNotification(n) { response.notification = n; return this; },
      build: () => response
    };
  }
};

// --- load the add-on, unmodified --------------------------------------------

['Prompts.gs', 'Code.gs'].forEach(file => {
  const src = fs.readFileSync(path.join(__dirname, file), 'utf8');
  // Apps Script concatenates files into one global scope; indirect eval does the same.
  (0, eval)(src);
});

// --- drive it ---------------------------------------------------------------

const B = s => `\x1b[1m${s}\x1b[0m`;
const D = s => `\x1b[2m${s}\x1b[0m`;
const G = s => `\x1b[32m${s}\x1b[0m`;
const R = s => `\x1b[31m${s}\x1b[0m`;
const rule = () => console.log(D('─'.repeat(74)));

function loadDotenv() {
  const p = path.join(__dirname, '..', '.env');
  if (!fs.existsSync(p)) return;
  fs.readFileSync(p, 'utf8').split('\n').forEach(line => {
    const m = /^([A-Z_]+)=(.*)$/.exec(line.trim());
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^['"]|['"]$/g, '');
  });
}

function main() {
  loadDotenv();
  if (!process.env.SUPERDOCS_API_KEY) {
    console.error(R('No SUPERDOCS_API_KEY. Put it in ../.env or the environment.'));
    process.exit(2);
  }

  console.log();
  rule();
  console.log(B('The add-on, running its real code against the live API'));
  console.log(D(`thread: ${path.basename(threadPath)} · ${MESSAGES.length} messages`));
  console.log(D(`subject: ${MESSAGES[0].subject}`));
  rule();

  console.log(B('\n1. Sidebar when you open the thread'));
  const opening = onGmailMessageOpen({ gmail: { messageId: '1' } });
  render(opening);

  console.log(B('\n2. You press "Find commitments"'));
  console.log(D('   one operation…'));
  const listing = onFindCommitments({ parameters: { messageId: '1' } });
  render(listing);

  const selection = findSelection(listing);
  const ticked = (selection ? selection.items : []).filter(i => i.selected);
  console.log(D(`   ${ticked.length} of ${(selection ? selection.items : []).length} pre-ticked`));

  console.log(B('\n3. You press "Write letter and attach to reply"'));
  console.log(D('   one operation…'));
  const rows = JSON.parse(buttonParams(listing).rows);
  const response = onWriteLetter({
    parameters: { messageId: '1', rows: JSON.stringify(rows) },
    formInput: { chosen: ticked.map(i => i.value) }
  });
  console.log('   ' + G(response.notification.setText || response.notification.text));

  console.log(B('\n4. The draft it put in your Gmail drafts'));
  rule();
  DRAFTS.forEach(d => {
    console.log(d.body.trimEnd());
    d.attachments.forEach(a => console.log(D(`\n[attachment: ${a.getName()}]`)));
  });
  rule();

  console.log(B('\nCalls it made to SuperDocs'));
  CALLS.forEach(c => {
    const ok = c.code < 400 ? G(String(c.code)) : R(String(c.code));
    console.log(`  ${c.method.padEnd(5)} ${c.url.replace('https://api.superdocs.app', '').padEnd(30)} ${ok}  ${(c.ms / 1000).toFixed(1)}s`);
  });
  console.log(D(`\n  ${CALLS.filter(c => c.url.includes('/chat')).length} operations spent. Exports are free.`));
  console.log(D('\nThis ran Code.gs and Prompts.gs unmodified. What it does not prove is'));
  console.log(D("Google's own binding: that their runtime renders these cards and delivers"));
  console.log(D('these events. Everything above is the add-on.\n'));
}

function render(card) {
  card.sections.forEach(section => section.widgets.forEach(w => {
    if (w.kind === 'paragraph') {
      console.log('   ' + strip(w.setText).replace(/\n/g, '\n   '));
    } else if (w.kind === 'button') {
      console.log('   ' + D(`[ ${w.setText} ]`));
    } else if (w.kind === 'selection') {
      (w.items || []).forEach(i => {
        const box = i.selected ? G('[x]') : '[ ]';
        console.log(`   ${box} ${i.label}`);
      });
    }
  }));
}

const strip = s => String(s || '').replace(/<br\s*\/?>/g, '\n').replace(/<[^>]+>/g, '');
const findSelection = card => {
  for (const s of card.sections) for (const w of s.widgets) if (w.kind === 'selection') return w;
  return null;
};
const buttonParams = card => {
  for (const s of card.sections) for (const w of s.widgets)
    if (w.kind === 'button' && w.setOnClickAction) return w.setOnClickAction.setParameters || {};
  return {};
};

main();
