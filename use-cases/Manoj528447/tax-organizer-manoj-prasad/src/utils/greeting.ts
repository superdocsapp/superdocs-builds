/**
 * Derives a name safe to use in a client-facing greeting ("Dear ___,").
 *
 * Regression guard for a real bug: when extraction couldn't identify a
 * client name, clientName was falling back to the raw uploaded filename
 * (e.g. "extra.pdf"), producing "Dear extra.pdf," in a real letter -- a
 * genuine bug a CPA could accidentally send to a client, not just a
 * cosmetic one. clientName itself is now never set to a raw filename (see
 * server.ts), but this stays defensive: it also catches generic
 * placeholder names (e.g. "Extracted Client Document", "Unidentified
 * Client") and filename-shaped strings, and normalizes all of them to a
 * clean, professional "Valued Client" rather than surfacing a fragment of
 * whatever placeholder or filename text happens to be in clientName.
 */
export function getGreetingName(clientName: string | undefined | null): string {
  const trimmed = (clientName || '').trim();

  if (!trimmed) return 'Valued Client';

  // Filename-shaped (has a short alphabetic "extension" at the end, e.g.
  // "extra.pdf", "return.docx") -- never greet with this.
  if (/\.[a-zA-Z]{2,4}$/.test(trimmed)) return 'Valued Client';

  // Known generic/placeholder names used elsewhere in the codebase when
  // extraction found nothing usable -- these read fine as a card title
  // ("Extracted Client Document") but not as a greeting ("Dear Extracted,").
  const genericPlaceholders = [
    'extracted client',
    'extracted client document',
    'unidentified client',
    'uploaded tax return client',
    'valued client'
  ];
  if (genericPlaceholders.includes(trimmed.toLowerCase())) return 'Valued Client';

  const firstToken = trimmed.split(/\s+/)[0];

  // A single-word name that isn't a normal first-name shape (contains
  // digits, underscores, or is unusually long -- likely a stray filename
  // fragment or ID rather than an actual first name).
  if (trimmed.split(/\s+/).length === 1 && (/[\d_]/.test(firstToken) || firstToken.length > 20)) {
    return 'Valued Client';
  }

  return firstToken;
}

/**
 * Formats a list of schedules/forms for inclusion in a sentence like
 * "your 2024 tax return (${...})". Regression guard for a real bug: when
 * schedulesApplied was empty, `arr.join(', ')` produced an empty string,
 * leaving a literal, ungrammatical "()" in client-facing letter text.
 * Returns an empty string (caller should omit the parens entirely) when
 * there's nothing to list, rather than a pair of empty parens.
 */
export function formatScheduleList(schedules: string[] | undefined | null): string {
  if (!schedules || schedules.length === 0) return '';
  return schedules.join(', ');
}
