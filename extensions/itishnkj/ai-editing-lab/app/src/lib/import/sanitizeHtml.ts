const ALLOWED_TAGS = new Set([
  'a',
  'blockquote',
  'br',
  'table',
  'thead',
  'tbody',
  'tfoot',
  'tr',
  'th',
  'td',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'li',
  'ol',
  'p',
  'strong',
  'u',
  'ul',
]);

const REMOVE_WITH_CONTENT = new Set([
  'applet',
  'embed',
  'iframe',
  'object',
  'script',
  'style',
  'svg',
]);

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function safeUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (/^(https?:|mailto:|\/|#)/i.test(trimmed)) return trimmed;
  return null;
}

function safeSpan(value: string): string | null {
  if (!/^(?:[1-9]|[1-9][0-9]|100)$/.test(value.trim())) return null;
  return String(Number(value));
}

function safeHeaderScope(value: string): string | null {
  return /^(?:col|row|colgroup|rowgroup)$/i.test(value.trim())
    ? value.trim().toLowerCase()
    : null;
}

function sanitizeElement(element: Element): void {
  const tag = element.tagName.toLowerCase();
  if (REMOVE_WITH_CONTENT.has(tag)) {
    element.remove();
    return;
  }

  for (const child of [...element.children]) sanitizeElement(child);

  if (!ALLOWED_TAGS.has(tag)) {
    element.replaceWith(...Array.from(element.childNodes));
    return;
  }

  for (const attribute of [...element.attributes]) {
    const name = attribute.name.toLowerCase();
    const value = attribute.value;
    const keepChunkId =
      name === 'data-chunk-id' && /^[a-z0-9][a-z0-9_-]{0,127}$/i.test(value);
    const keepLink = tag === 'a' && name === 'href' && safeUrl(value);
    const keepCellSpan =
      (tag === 'td' || tag === 'th') &&
      (name === 'colspan' || name === 'rowspan') &&
      safeSpan(value);
    const keepHeaderScope =
      tag === 'th' && name === 'scope' && safeHeaderScope(value);
    if (keepChunkId || keepLink || keepCellSpan || keepHeaderScope) continue;
    element.removeAttribute(attribute.name);
  }
}

/**
 * Keeps TipTap-compatible semantic formatting, tables, and the provider's
 * legitimate data-chunk-id metadata while removing executable uploaded markup.
 */
export function sanitizeImportedHtml(input: string): string {
  if (typeof document === 'undefined') {
    // Keep the same narrow semantic allowlist for test/SSR environments.
    return input
      .replace(
        /<(applet|embed|iframe|object|script|style|svg)\b[^>]*>[\s\S]*?<\/\1\s*>/gi,
        '',
      )
      .replace(/<!--[\s\S]*?-->/g, '')
      .replace(/<\/?([a-z0-9-]+)\b([^>]*)>/gi, (whole, rawTag, rawAttributes) => {
        const tag = rawTag.toLowerCase();
        const isClosing = whole.startsWith('</');
        if (!ALLOWED_TAGS.has(tag)) return '';
        if (isClosing) return `</${tag}>`;
        const chunk = rawAttributes.match(
          /\bdata-chunk-id\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i,
        );
        const href = rawAttributes.match(
          /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i,
        );
        const colspan = rawAttributes.match(
          /\bcolspan\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i,
        );
        const rowspan = rawAttributes.match(
          /\browspan\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i,
        );
        const scope = rawAttributes.match(
          /\bscope\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i,
        );
        const attributes: string[] = [];
        const chunkValue = chunk?.[1] ?? chunk?.[2] ?? chunk?.[3];
        const hrefValue = href?.[1] ?? href?.[2] ?? href?.[3];
        const colspanValue = colspan?.[1] ?? colspan?.[2] ?? colspan?.[3];
        const rowspanValue = rowspan?.[1] ?? rowspan?.[2] ?? rowspan?.[3];
        const scopeValue = scope?.[1] ?? scope?.[2] ?? scope?.[3];
        if (
          chunkValue &&
          /^[a-z0-9][a-z0-9_-]{0,127}$/i.test(chunkValue)
        ) {
          attributes.push(`data-chunk-id="${escapeHtml(chunkValue)}"`);
        }
        if (tag === 'a' && hrefValue && safeUrl(hrefValue)) {
          attributes.push(`href="${escapeHtml(hrefValue)}"`);
        }
        if ((tag === 'td' || tag === 'th') && colspanValue && safeSpan(colspanValue)) {
          attributes.push(`colspan="${safeSpan(colspanValue)}"`);
        }
        if ((tag === 'td' || tag === 'th') && rowspanValue && safeSpan(rowspanValue)) {
          attributes.push(`rowspan="${safeSpan(rowspanValue)}"`);
        }
        if (tag === 'th' && scopeValue && safeHeaderScope(scopeValue)) {
          attributes.push(`scope="${safeHeaderScope(scopeValue)}"`);
        }
        return `<${tag}${attributes.length ? ` ${attributes.join(' ')}` : ''}>`;
      })
      .trim();
  }

  const template = document.createElement('template');
  template.innerHTML = input;
  for (const child of [...template.content.children]) sanitizeElement(child);
  return template.innerHTML.trim();
}