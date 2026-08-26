export type Weight = 'shared' | 'vertical'

export type DivergenceReport = {
  evaluation: {
    passed: boolean
    failures: string[]
    mean_vertical_overlap: number
    mean_shared_overlap: number
    thresholds: {
      vertical_mean_max: number
      vertical_section_max: number
      shared_sections_gated: boolean
    }
  }
  report: {
    aggregates: {
      mean_vertical_overlap: number
      mean_shared_overlap: number
      vertical_cells: number
      shared_cells: number
    }
    pairs: Array<{
      vertical_a: string
      vertical_b: string
      sections: Record<string, number>
    }>
  }
  section_weights: Record<string, Weight>
  verticals: string[]
  coverage_notes?: Array<{ vertical: string; section: string; issue: string }>
}

export const SECTION_TITLES: Record<string, string> = {
  '1': 'Opening / Hook',
  '2': 'The Problem',
  '3': 'Why Now',
  '4': 'Product Overview',
  '5': 'How ClarityDocs Solves It',
  '6': 'Proof / Case Study',
  '7': 'Objection Handling',
  '8': 'ROI / Business Case',
  '9': 'Call to Action',
}

export function pairLabel(a: string, b: string): string {
  const short = (s: string) => s.slice(0, 3)
  return `${short(a)}–${short(b)}`
}

export function fmt(n: number): string {
  return n.toFixed(3)
}
