export type Screen = 'divergence' | 'verticals' | 'generate' | 'narratives'

const KNOWN: Screen[] = ['divergence', 'verticals', 'generate', 'narratives']

export function parseHash(hash: string = window.location.hash): Screen {
  const raw = hash.replace(/^#\/?/, '').split('/')[0]?.toLowerCase() ?? ''
  if (KNOWN.includes(raw as Screen)) return raw as Screen
  return 'divergence'
}

export function hrefFor(screen: Screen): string {
  return `#/${screen}`
}
