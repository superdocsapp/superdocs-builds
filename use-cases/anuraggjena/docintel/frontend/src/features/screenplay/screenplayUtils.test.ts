import { describe, it, expect } from 'vitest'
import { extractCharacters, extractScenes } from './screenplayUtils'
import type { FormattingItem } from '@/core/api/screenplayApi'

function createMockItem(partial: Partial<FormattingItem>): FormattingItem {
  return {
    id: 'item-1',
    element_index: 0,
    element_type: 'action',
    formatted_text: '',
    original_text: '',
    change_type: 'no_change',
    reason: '',
    scene_number: null,
    character_name: null,
    diff_tokens: [],
    content_drift: false,
    status: 'approved',
    reviewer_comment: null,
    confidence_score: 1.0,
    created_at: '',
    updated_at: '',
    ...partial,
  }
}

describe('screenplayUtils character extraction & normalization', () => {
  it('deduplicates character cues and returns exact normalized character list with matching count', () => {
    const items: FormattingItem[] = [
      createMockItem({
        id: '1',
        element_index: 0,
        element_type: 'scene_heading',
        formatted_text: 'INT. NSA FIELD OFFICE - NIGHT',
        original_text: 'INT. NSA FIELD OFFICE - NIGHT',
        scene_number: 1,
      }),
      createMockItem({
        id: '2',
        element_index: 1,
        element_type: 'character',
        formatted_text: 'RAINES',
        original_text: 'RAINES',
        character_name: 'RAINES',
      }),
      createMockItem({
        id: '3',
        element_index: 2,
        element_type: 'dialogue',
        formatted_text: "We've got confirmation.",
        original_text: "We've got confirmation.",
        character_name: 'RAINES',
      }),
      createMockItem({
        id: '4',
        element_index: 3,
        element_type: 'character',
        formatted_text: 'DANA (V.O.)',
        original_text: 'DANA (V.O.)',
        character_name: 'DANA',
      }),
      createMockItem({
        id: '5',
        element_index: 4,
        element_type: 'dialogue',
        formatted_text: "It's always a glitch until it isn't.",
        original_text: "It's always a glitch until it isn't.",
        character_name: 'DANA',
      }),
      createMockItem({
        id: '6',
        element_index: 5,
        element_type: 'character',
        formatted_text: "RAINES (CONT'D)",
        original_text: "RAINES (CONT'D)",
        character_name: 'RAINES',
      }),
      createMockItem({
        id: '7',
        element_index: 6,
        element_type: 'dialogue',
        formatted_text: 'Three separate relay stations.',
        original_text: 'Three separate relay stations.',
        character_name: 'RAINES',
      }),
      createMockItem({
        id: '8',
        element_index: 7,
        element_type: 'character',
        formatted_text: 'INVESTIGATOR #1',
        original_text: 'INVESTIGATOR #1',
        character_name: 'INVESTIGATOR #1',
      }),
      createMockItem({
        id: '9',
        element_index: 8,
        element_type: 'dialogue',
        formatted_text: 'State your name.',
        original_text: 'State your name.',
        character_name: 'INVESTIGATOR #1',
      }),
    ]

    const characters = extractCharacters(items)

    expect(characters).toHaveLength(3)
    expect(characters.map((c) => c.name)).toEqual(['Raines', 'Dana', 'Investigator #1'])
    
    const raines = characters.find((c) => c.name === 'Raines')
    const dana = characters.find((c) => c.name === 'Dana')
    const inv1 = characters.find((c) => c.name === 'Investigator #1')

    expect(raines?.dialogueCount).toBe(2)
    expect(dana?.dialogueCount).toBe(1)
    expect(inv1?.dialogueCount).toBe(1)
    expect(inv1?.initials).toBe('I1')
  })

  it('filters out non-character terms and transitions', () => {
    const items: FormattingItem[] = [
      createMockItem({ id: '1', element_index: 0, element_type: 'title', formatted_text: 'THE LAST SIGNAL', original_text: 'THE LAST SIGNAL' }),
      createMockItem({ id: '2', element_index: 1, element_type: 'transition', formatted_text: 'FADE OUT.', original_text: 'FADE OUT.' }),
      createMockItem({ id: '3', element_index: 2, element_type: 'transition', formatted_text: 'END MONTAGE.', original_text: 'END MONTAGE.' }),
      createMockItem({ id: '4', element_index: 3, element_type: 'transition', formatted_text: 'LATER - DAY', original_text: 'LATER - DAY' }),
      createMockItem({ id: '5', element_index: 4, element_type: 'end', formatted_text: 'THE END', original_text: 'THE END' }),
      createMockItem({ id: '6', element_index: 5, element_type: 'character', formatted_text: 'BRECK', original_text: 'BRECK', character_name: 'BRECK' }),
      createMockItem({ id: '7', element_index: 6, element_type: 'dialogue', formatted_text: 'Ready.', original_text: 'Ready.', character_name: 'BRECK' }),
    ]

    const characters = extractCharacters(items)
    expect(characters).toHaveLength(1)
    expect(characters[0].name).toBe('Breck')
  })
})

describe('screenplayUtils scene extraction', () => {
  it('extracts unique scenes and filters out secondary subheaders and duplicate scene numbers', () => {
    const items: FormattingItem[] = [
      createMockItem({
        id: '1',
        element_index: 0,
        element_type: 'scene_heading',
        formatted_text: 'INT. NSA FIELD OFFICE - LANGLEY, VIRGINIA - NIGHT',
        scene_number: 1,
      }),
      createMockItem({
        id: '2',
        element_index: 1,
        element_type: 'action',
        formatted_text: 'The office hums with fluorescent lights.',
        scene_number: 1,
      }),
      createMockItem({
        id: '3',
        element_index: 2,
        element_type: 'scene_heading',
        formatted_text: 'EXT. BUCHAREST ROOFTOP - NIGHT',
        scene_number: 2,
      }),
      createMockItem({
        id: '4',
        element_index: 3,
        element_type: 'scene_heading',
        formatted_text: 'MONTAGE -- DANA AND RAINES WORK THE CASE:',
        scene_number: 2,
      }),
      createMockItem({
        id: '5',
        element_index: 4,
        element_type: 'scene_heading',
        formatted_text: 'INT. INSPECTOR GENERAL ROOM - DAY',
        scene_number: 3,
      }),
      createMockItem({
        id: '6',
        element_index: 5,
        element_type: 'scene_heading',
        formatted_text: 'LATER - DAY',
        scene_number: 3,
      }),
    ]

    const scenes = extractScenes(items)
    expect(scenes).toHaveLength(3)
    expect(scenes.map((s) => s.sceneNumber)).toEqual([1, 2, 3])
    expect(scenes[0].heading).toBe('INT. NSA FIELD OFFICE - LANGLEY, VIRGINIA - NIGHT')
    expect(scenes[1].heading).toBe('EXT. BUCHAREST ROOFTOP - NIGHT')
    expect(scenes[2].heading).toBe('INT. INSPECTOR GENERAL ROOM - DAY')
  })
})
