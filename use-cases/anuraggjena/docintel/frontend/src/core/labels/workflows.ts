const WORKFLOW_SLUG: Record<string, string> = {
  tariff_classification: 'Tariff Classification',
  tariff: 'Tariff Classification',
  'tariff-classification': 'Tariff Classification',
  screenplay: 'Screenplay Formatting',
  screenplay_formatting: 'Screenplay Formatting',
  'screenplay-formatting': 'Screenplay Formatting',
}

export function formatWorkflowSlug(slug?: string | null): string {
  if (!slug || slug === 'workflow') return 'Tariff Classification'
  return WORKFLOW_SLUG[slug] ?? slug.replace(/[-_]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}
