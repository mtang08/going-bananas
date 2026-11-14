import { describe, expect, it } from 'vitest'
import guide from 'virtual:user-guide'
import { CATEGORY_LABELS, LADDER_LABELS, SEVERITY_LABELS, operationLabel } from '../src/coachLabels'
import { BENCHMARK_PROMPT, WEEKLY_PROMPT, racePrompt } from '../src/coachPrompts'

describe('coach labels and prompts', () => {
  it('label maps cover every enum value', () => {
    expect(Object.keys(CATEGORY_LABELS)).toEqual([
      'symptoms_illness',
      'training_response',
      'accumulated_fatigue',
      'calendar_disruption',
      'post_event',
    ])
    expect(Object.keys(SEVERITY_LABELS)).toEqual(['observe', 'caution', 'hold', 'escalate'])
    expect(Object.keys(LADDER_LABELS)).toEqual([
      'current_session',
      'next_session',
      'next_days',
      'committed_window',
      'block',
    ])
  })

  it('escalate reads as a bigger review', () => {
    expect(SEVERITY_LABELS.escalate).toBe('Needs bigger review')
  })

  it('operation labels fall back to spaced names', () => {
    expect(operationLabel('exception_review')).toBe('Exception review')
    expect(operationLabel('new_op')).toBe('new op')
  })

  it('race prompt names the event', () => {
    expect(racePrompt('City 10K', '2026-12-06')).toBe(
      'Use $going-bananas-coach for a post-race review of City 10K on 2026-12-06.',
    )
  })

  it('weekly prompt matches the user guide', () => {
    expect(guide.includes('> ' + WEEKLY_PROMPT)).toBe(true)
  })

  it('benchmark prompt matches the contract', () => {
    expect(BENCHMARK_PROMPT).toBe(
      'Use $going-bananas-coach for a block review. Review the block benchmark.',
    )
  })
})
