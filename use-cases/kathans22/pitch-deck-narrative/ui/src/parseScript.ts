export type Figure = {
  alt: string
  src: string
}

export type ScriptSection = {
  n: string
  title: string
  talkingPoint: string
  notes: string[]
  figures: Figure[]
}

export function rewriteFigureSrc(src: string): string {
  const cleaned = src.replace(/\\/g, '/').replace(/^\.\//, '')
  if (cleaned.startsWith('http') || cleaned.startsWith('/')) return cleaned
  return `/${cleaned}`
}

function stripDecor(s: string): string {
  return s.replace(/\*{1,2}/g, '').replace(/_/g, '').trim()
}

export function parseScript(md: string): ScriptSection[] {
  return md
    .split(/^##\s+/m)
    .slice(1)
    .map((chunk) => {
      const nl = chunk.indexOf('\n')
      const head = (nl === -1 ? chunk : chunk.slice(0, nl)).trim()
      const body = nl === -1 ? '' : chunk.slice(nl + 1)
      const hm = head.match(/^Slide-equivalent\s+(\d+)\s+[—–-]\s+(.+)$/i)
      const n = hm?.[1] ?? '?'
      const title = hm?.[2] ?? head
      const figures: Figure[] = []
      const imgRe = /!\[([^\]]*)\]\(([^)]+)\)/g
      let im: RegExpExecArray | null
      while ((im = imgRe.exec(body)) !== null) {
        figures.push({ alt: im[1], src: rewriteFigureSrc(im[2]) })
      }
      const talking = firstLabeled(body, /talking point/i)
      const notes = unique(
        collectLabeled(body, /(?:full\s+)?speaker notes/i).filter(
          (t) => t.length > 0 && !/PLACEHOLDER_/i.test(t),
        ),
      )
      return { n, title, talkingPoint: talking, notes, figures }
    })
}

function firstLabeled(body: string, label: RegExp): string {
  const found = collectLabeled(body, label)
  return found[0] ?? ''
}

function collectLabeled(body: string, label: RegExp): string[] {
  const out: string[] = []
  const re = /(?:\*{1,2}|_)([^:*\n]+)(?::)(?:\*{1,2}|_)?\s*/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(body)) !== null) {
    if (!label.test(m[1])) continue
    const start = m.index + m[0].length
    const rest = body.slice(start)
    const cut = rest.search(
      /\n(?:\*{1,2}|_)(?:Talking point|Speaker notes|Full speaker notes|Presenter visual)/i,
    )
    const raw = (cut === -1 ? rest : rest.slice(0, cut)).trim()
    const paragraph = stripDecor(
      raw
        .replace(/!\[[^\]]*\]\([^)]+\)/g, '')
        .replace(/PLACEHOLDER_[A-Z0-9_]+/g, '')
        .trim(),
    )
    if (paragraph) out.push(paragraph)
  }
  return out
}

function unique(items: string[]): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const item of items) {
    const key = item.slice(0, 160)
    if (seen.has(key)) continue
    seen.add(key)
    out.push(item)
  }
  return out
}
