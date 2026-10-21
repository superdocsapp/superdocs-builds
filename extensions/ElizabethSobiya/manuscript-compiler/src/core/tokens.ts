/**
 * Numbering tokens.
 *
 * A chapter is rendered ONCE into HTML that still carries *tokens* where numbers
 * belong — `Figure <fig:origins-map>`, not `Figure 3.1`. Numbers are assigned in a
 * single assembly pass over the ordered chapters.
 *
 * Why: figure 12 becoming figure 13 because chapter 2 gained a plate must not
 * invalidate chapter 9's cached render. With tokens, a chapter's rendered bytes
 * depend only on that chapter's own source, so the incremental report can state,
 * truthfully, which chapters were re-rendered and which were merely renumbered.
 *
 * The delimiters live in the Unicode Private Use Area so they cannot collide with
 * anything a human would type. Any stray PUA characters in source notes are
 * stripped at ingest (see sanitizeSource) so a note can never forge a token.
 */

export const TOKEN_OPEN = "\uE000";
export const TOKEN_CLOSE = "\uE001";

export type TokenKind =
  | "fig" // the figure's own number, at its caption
  | "figref" // a cross-reference to a figure
  | "fn" // a footnote marker in the body
  | "fnbody" // the number printed at the start of an endnote body
  | "cite" // a rendered citation
  | "secref"; // a cross-reference to a heading

export interface Token {
  kind: TokenKind;
  /** Payload: figure key, footnote key, cite key + locator, heading anchor. */
  payload: string;
}

export function token(kind: TokenKind, payload: string): string {
  return `${TOKEN_OPEN}${kind}:${payload}${TOKEN_CLOSE}`;
}

const TOKEN_RE = new RegExp(`${TOKEN_OPEN}([a-z]+):([^${TOKEN_CLOSE}]*)${TOKEN_CLOSE}`, "g");

/** Replace every token in `html` using `resolve`. Unknown tokens are left to the resolver. */
export function resolveTokens(html: string, resolve: (t: Token) => string): string {
  TOKEN_RE.lastIndex = 0;
  return html.replace(TOKEN_RE, (_m, kind: string, payload: string) =>
    resolve({ kind: kind as TokenKind, payload }),
  );
}

/** Every token present, in document order. Used by tests and by the numbering pass. */
export function scanTokens(html: string): Token[] {
  const out: Token[] = [];
  TOKEN_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = TOKEN_RE.exec(html)) !== null) {
    out.push({ kind: m[1] as TokenKind, payload: m[2]! });
  }
  return out;
}

/**
 * Strip Private Use Area characters from source text.
 *
 * This is a small but load-bearing guarantee: without it, a note containing a raw
 * U+E000 could inject a numbering token and make the compiler print a number that
 * no figure owns. The compiler must never emit a number it cannot trace to a real
 * figure, footnote or bibliography entry.
 */
export function sanitizeSource(text: string): string {
  return text.replace(/[\uE000-\uF8FF]/g, "");
}

export function hasTokens(html: string): boolean {
  TOKEN_RE.lastIndex = 0;
  return TOKEN_RE.test(html);
}
