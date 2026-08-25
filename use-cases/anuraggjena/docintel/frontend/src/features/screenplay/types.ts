export interface ScreenplayScene {
  sceneNumber: number
  heading: string
  elementIndex: number
  page: number
  elementsCount: number
}

export interface ScreenplayCharacter {
  name: string
  initials: string
  dialogueCount: number
  colorClass: string
  bgClass: string
  borderClass: string
}

export interface ScreenplayAnalysisMetrics {
  scenesCount: number
  pagesCount: number
  wordsCount: number
  formattingScore: number
}

export interface ScreenplayIssueCategory {
  id: string
  title: string
  count: number
  dotColor: string
  description: string
}

export type ScreenplayViewMode = 'formatted' | 'source'

export type ChangeFilterTab = 'all' | 'accepted' | 'pending' | 'rejected'
