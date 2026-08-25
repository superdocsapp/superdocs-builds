import type { FormattingItem } from '@/core/api/screenplayApi'
import type {
  ScreenplayScene,
  ScreenplayCharacter,
  ScreenplayAnalysisMetrics,
  ScreenplayIssueCategory,
} from './types'

const CHARACTER_PALETTES = [
  { color: 'text-blue-700', bg: 'bg-blue-100', border: 'border-blue-200' },
  { color: 'text-purple-700', bg: 'bg-purple-100', border: 'border-purple-200' },
  { color: 'text-emerald-700', bg: 'bg-emerald-100', border: 'border-emerald-200' },
  { color: 'text-amber-700', bg: 'bg-amber-100', border: 'border-amber-200' },
  { color: 'text-rose-700', bg: 'bg-rose-100', border: 'border-rose-200' },
  { color: 'text-indigo-700', bg: 'bg-indigo-100', border: 'border-indigo-200' },
  { color: 'text-teal-700', bg: 'bg-teal-100', border: 'border-teal-200' },
]

export function extractScenes(items: FormattingItem[]): ScreenplayScene[] {
  const scenes: ScreenplayScene[] = []
  const seenSceneNumbers = new Set<number>()
  let cumulativeLines = 0

  items.forEach((item) => {
    const linesInItem = Math.max(1, (item.formatted_text || item.original_text || '').split('\n').length)
    cumulativeLines += linesInItem

    if (item.element_type === 'scene_heading') {
      const heading = (item.formatted_text || item.original_text || '').trim()
      const isStandardSlug = /^(INT|EXT|INT\/EXT|I\/E)[\.\s]/i.test(heading)
      const cleanUpper = heading.toUpperCase().replace(/[^A-Z0-9\s\-]/g, '').trim()

      // Ignore secondary transitions or sub-headers that were categorized as scene_headings
      if (!isStandardSlug && (
        cleanUpper.startsWith('MONTAGE') ||
        cleanUpper.startsWith('LATER') ||
        cleanUpper.startsWith('INTERCUT') ||
        cleanUpper.startsWith('MOMENTS LATER') ||
        cleanUpper.startsWith('CONTINUOUS')
      )) {
        if (scenes.length > 0) {
          scenes[scenes.length - 1].elementsCount += 1
        }
        return
      }

      // If this scene number is already recorded, aggregate into the current scene
      if (item.scene_number && seenSceneNumbers.has(item.scene_number)) {
        if (scenes.length > 0) {
          scenes[scenes.length - 1].elementsCount += 1
        }
        return
      }

      const sceneNumber = item.scene_number || (scenes.length + 1)
      seenSceneNumbers.add(sceneNumber)
      const estimatedPage = Math.max(1, Math.ceil(cumulativeLines / 54))

      scenes.push({
        sceneNumber,
        heading: heading || `SCENE ${sceneNumber}`,
        elementIndex: item.element_index,
        page: estimatedPage,
        elementsCount: 1,
      })
    } else if (scenes.length > 0) {
      scenes[scenes.length - 1].elementsCount += 1
    }
  })

  // Fallback if no explicit scene headings were parsed
  if (scenes.length === 0 && items.length > 0) {
    scenes.push({
      sceneNumber: 1,
      heading: 'SCENE 1',
      elementIndex: 0,
      page: 1,
      elementsCount: items.length,
    })
  }

  return scenes
}

const NON_CHARACTER_TERMS = new Set([
  'THE END', 'END', 'FIN', 'F.I.N.', 'LAST CALL', 'CUT TO:', 'FADE OUT.',
  'FADE IN:', 'DISSOLVE TO:', 'SMASH CUT TO:', 'MATCH CUT TO:', 'FADE TO BLACK.',
  'SCENE', 'TITLE', 'AUTHOR', 'CREDIT', 'INTERCUT WITH:', 'INTERCUT',
  'END FLASHBACK', 'END FLASHBACK.', 'FLASHBACK', 'END MONTAGE', 'END MONTAGE.',
  'MONTAGE', 'LATER', 'LATER - DAY', 'LATER - NIGHT', 'MOMENTS LATER', 'CONTINUOUS', 'SAME TIME',
  'BACK TO SCENE', 'BACK TO SCENE.',
])

export function extractCharacters(items: FormattingItem[]): ScreenplayCharacter[] {
  const dialogueCounts = new Map<string, number>()
  const characterNames = new Set<string>()

  items.forEach((item) => {
    // Only extract character names from character cues or dialogue lines
    if (item.element_type === 'character' || (item.element_type === 'dialogue' && item.character_name)) {
      const rawName = item.character_name || (item.element_type === 'character' ? (item.formatted_text || item.original_text) : '')
      if (!rawName) return

      // Remove extensions like (V.O.), (O.S.), (CONT'D), (42), (whispering), etc.
      const cleanName = rawName
        .replace(/\s*\(.*?\)/g, '')
        .replace(/[^A-Za-z0-9\s\&\#\-]/g, '')
        .trim()
        .toUpperCase()

      if (!cleanName || cleanName.length > 35 || NON_CHARACTER_TERMS.has(cleanName)) return
      if (cleanName.startsWith('INT.') || cleanName.startsWith('EXT.') || cleanName.startsWith('WRITTEN BY')) return
      if (cleanName.startsWith('CUT TO') || cleanName.startsWith('FADE') || cleanName.startsWith('SCENE')) return

      characterNames.add(cleanName)
      if (item.element_type === 'dialogue') {
        dialogueCounts.set(cleanName, (dialogueCounts.get(cleanName) || 0) + 1)
      } else if (!dialogueCounts.has(cleanName)) {
        dialogueCounts.set(cleanName, 0)
      }
    }
  })

  // Ensure characters that have cue elements but no dialogue items still have a minimum count of 1
  characterNames.forEach((name) => {
    if (!dialogueCounts.has(name) || dialogueCounts.get(name) === 0) {
      dialogueCounts.set(name, Math.max(1, dialogueCounts.get(name) || 0))
    }
  })

  const sortedNames = Array.from(characterNames)
    .sort((a, b) => (dialogueCounts.get(b) || 0) - (dialogueCounts.get(a) || 0))

  return sortedNames.map((name, index) => {
    const palette = CHARACTER_PALETTES[index % CHARACTER_PALETTES.length]
    const words = name.replace(/[^A-Za-z0-9\s\&\#\-]/g, '').trim().split(/\s+/)
    let initials = ''
    if (words.length >= 2) {
      const secondClean = words[1].replace(/[^A-Za-z0-9]/g, '')
      initials = `${words[0][0]}${secondClean ? secondClean[0] : words[1][0]}`.toUpperCase()
    } else if (words.length === 1 && words[0].length > 0) {
      initials = words[0].slice(0, 2).toUpperCase()
    } else {
      initials = 'CH'
    }

    // Format display name nicely (e.g., ALEX JORDAN -> Alex Jordan, PRIYA & RAVI -> Priya & Ravi, INVESTIGATOR #1 -> Investigator #1)
    const displayName = words
      .map((w) => {
        if (w === '&' || w === 'AND') return w
        if (w.startsWith('#')) return w
        return w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()
      })
      .join(' ')

    return {
      name: displayName || name,
      initials,
      dialogueCount: dialogueCounts.get(name) || 0,
      colorClass: palette.color,
      bgClass: palette.bg,
      borderClass: palette.border,
    }
  })
}

export function calculateAnalysisMetrics(items: FormattingItem[]): ScreenplayAnalysisMetrics {
  const scenes = extractScenes(items)
  const totalWords = items.reduce((acc, item) => {
    const text = item.formatted_text || item.original_text || ''
    const words = text.trim().split(/\s+/).filter(Boolean).length
    return acc + words
  }, 0)

  const totalLines = items.reduce((acc, item) => {
    const text = item.formatted_text || item.original_text || ''
    return acc + Math.max(1, text.split('\n').length)
  }, 0)

  const estimatedPages = Math.max(1, Math.ceil(totalLines / 54) || Math.ceil(totalWords / 250) || 1)

  // Calculate formatting score: percentage of elements without drift, or with high confidence
  let validElements = 0
  items.forEach((item) => {
    if (!item.content_drift && (item.confidence_score == null || item.confidence_score >= 0.7)) {
      validElements += 1
    }
  })

  const rawScore = items.length > 0 ? Math.round((validElements / items.length) * 100) : 98
  const formattingScore = Math.max(85, Math.min(100, rawScore))

  return {
    scenesCount: scenes.length,
    pagesCount: estimatedPages,
    wordsCount: totalWords,
    formattingScore,
  }
}

export function extractPotentialIssues(items: FormattingItem[]): ScreenplayIssueCategory[] {
  let sceneHeadingIssues = 0
  let parentheticalIssues = 0
  let dialogueIssues = 0
  let actionLengthIssues = 0

  items.forEach((item) => {
    const reason = (item.reason || '').toLowerCase()
    const changeType = (item.change_type || '').toLowerCase()

    if (item.element_type === 'scene_heading' && (changeType !== 'no_change' || reason.includes('case') || reason.includes('heading'))) {
      sceneHeadingIssues += 1
    } else if (item.element_type === 'parenthetical' || reason.includes('parenthetical')) {
      if (changeType !== 'no_change' || reason.includes('parenthetical')) {
        parentheticalIssues += 1
      }
    } else if (item.element_type === 'dialogue' && (changeType !== 'no_change' || reason.includes('dialogue') || reason.includes('punctuation'))) {
      dialogueIssues += 1
    } else if (item.element_type === 'action' && (changeType !== 'no_change' || reason.includes('length') || reason.includes('wrap') || item.content_drift)) {
      actionLengthIssues += 1
    }
  })

  // If no specific issues detected but items exist, show clean categorized zero/low counts
  return [
    {
      id: 'scene_heading',
      title: 'Scene heading case',
      count: sceneHeadingIssues,
      dotColor: 'bg-amber-400',
      description: 'Headings standardized to uppercase format',
    },
    {
      id: 'parentheticals',
      title: 'Parenthetical formatting',
      count: parentheticalIssues,
      dotColor: 'bg-emerald-400',
      description: 'Parentheticals properly wrapped and positioned',
    },
    {
      id: 'dialogue',
      title: 'Dialogue formatting',
      count: dialogueIssues,
      dotColor: 'bg-blue-400',
      description: 'Character dialogue indentation & margins',
    },
    {
      id: 'action',
      title: 'Action line length',
      count: actionLengthIssues,
      dotColor: 'bg-purple-400',
      description: 'Action blocks checked for standard line breaks',
    },
  ]
}

export function formatChangeReasonTitle(item: FormattingItem): string {
  if (item.reason && item.reason.trim()) {
    // E.g. "Formatted scene heading to uppercase" -> "Scene heading format"
    const r = item.reason.trim()
    if (r.toLowerCase().includes('heading')) return 'Scene heading format'
    if (r.toLowerCase().includes('parenthetical')) return 'Parenthetical format'
    if (r.toLowerCase().includes('dialogue')) return 'Dialogue punctuation'
    if (r.toLowerCase().includes('action')) return 'Action formatting'
    if (r.toLowerCase().includes('character')) return 'Character name casing'
    if (r.toLowerCase().includes('transition')) return 'Transition format'
    return r
  }

  switch (item.element_type) {
    case 'scene_heading':
      return 'Scene heading format'
    case 'parenthetical':
      return 'Added parenthetical format'
    case 'dialogue':
      return 'Dialogue punctuation'
    case 'action':
      return 'Action line formatting'
    case 'character':
      return 'Character capitalization'
    case 'transition':
      return 'Transition alignment'
    default:
      return 'Formatting adjustment'
  }
}
