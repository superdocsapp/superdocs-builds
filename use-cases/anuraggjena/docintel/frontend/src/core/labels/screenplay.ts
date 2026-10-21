const ELEMENT_TYPE: Record<string, string> = {
  title: 'Title',
  author: 'Author',
  scene_heading: 'Scene Heading',
  action: 'Action',
  character: 'Character',
  dialogue: 'Dialogue',
  parenthetical: 'Parenthetical',
  transition: 'Transition',
  shot: 'Shot',
  page_number: 'Page Number',
  end: 'End',
  uncertain: 'Uncertain',
  other: 'Other',
}

const ELEMENT_BADGE: Record<string, string> = {
  title: 'bg-indigo-100 text-indigo-800',
  author: 'bg-sky-100 text-sky-800',
  scene_heading: 'bg-blue-100 text-blue-800',
  action: 'bg-gray-100 text-gray-700',
  character: 'bg-purple-100 text-purple-800',
  dialogue: 'bg-yellow-100 text-yellow-800',
  parenthetical: 'bg-orange-100 text-orange-800',
  transition: 'bg-pink-100 text-pink-800',
  shot: 'bg-cyan-100 text-cyan-800',
  page_number: 'bg-stone-100 text-stone-700',
  end: 'bg-slate-200 text-slate-800',
  uncertain: 'bg-red-100 text-red-700',
  other: 'bg-gray-100 text-gray-600',
}

export function formatElementType(elementType: string): string {
  return ELEMENT_TYPE[elementType] ?? elementType.replace(/_/g, ' ')
}

export function getElementBadgeClass(elementType: string): string {
  return ELEMENT_BADGE[elementType] ?? 'bg-gray-100 text-gray-600'
}
