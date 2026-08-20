// Teacher-facing review choices only. SuperDocs model names and thinking
// values deliberately stay in the backend; the browser sends these semantic
// values to the reviewed workflow API.

export const REVIEW_MODES = [
  {
    value: 'proofreading',
    label: 'Proofreading',
    description: 'Grammar, spelling and punctuation',
  },
  {
    value: 'writing_quality',
    label: 'Writing Quality',
    description: 'Clarity, structure and flow',
  },
  {
    value: 'academic_writing',
    label: 'Academic Writing',
    description: 'Academic style and coherence',
  },
  {
    value: 'custom',
    label: 'Custom',
    description: 'Your own review instructions',
  },
]

export const REVIEW_DEPTHS = [
  {
    value: 'quick',
    label: 'Quick',
    description: 'A focused review for straightforward writing tasks.',
  },
  {
    value: 'standard',
    label: 'Standard',
    description: 'A well-rounded review for most student work.',
  },
  {
    value: 'thorough',
    label: 'Thorough',
    description: 'A deeper review configuration for more involved writing tasks.',
  },
]

export const DEFAULT_REVIEW_MODE = 'proofreading'
export const DEFAULT_REVIEW_DEPTH = 'standard'

export function isCustomReview(mode) {
  return mode === 'custom'
}
