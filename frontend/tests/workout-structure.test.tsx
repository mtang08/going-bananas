import { afterEach, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { compactWorkout, WorkoutStructure } from '../src/components/WorkoutStructure'
import type { PlannedStep, StructureItem } from '../src/api'
const work: PlannedStep = { type: 'work', duration_type: 'time', duration_value: 180, target: { modality: 'effort', low: null, high: null, effort_cue: 'Controlled hard; stay relaxed' } }
const recovery: PlannedStep = { type: 'recovery', duration_type: 'time', duration_value: 120, target: null }
afterEach(cleanup)
it.each([false, true])('preserves five work reps and four recoveries (expanded=%s)', expanded => {
  const structure: StructureItem[] = expanded ? [...Array.from({ length: 4 }, () => [work, recovery]).flat(), work] : [{ type: 'repeat', count: 4, steps: [work, recovery] }, work]
  const original = JSON.stringify(structure)
  expect(compactWorkout(structure)).toEqual([{ steps: [expect.objectContaining(work), expect.objectContaining(recovery)], count: 5, recoveryBetween: true }])
  render(<WorkoutStructure structure={structure} unit="km" />)
  expect(screen.getByRole('listitem')).toHaveTextContent('5 × Work 3:00 · Controlled hard; stay relaxed')
  expect(screen.getByText(/Between reps \(4 recoveries\)/)).toBeInTheDocument()
  expect(JSON.stringify(structure)).toBe(original)
})
it('retains the last recovery in a complete repeat block', () => {
  render(<WorkoutStructure structure={[{ type: 'repeat', count: 5, steps: [work, recovery] }]} unit="km" />)
  expect(screen.getByText('Recovery after every rep, including the final rep.')).toBeInTheDocument()
  expect(screen.queryByText(/between reps/)).toBeNull()
})
it.each([
  { ...work, duration_value: 181 },
  { ...work, duration_type: 'distance' as const },
  { ...work, target: { ...work.target!, effort_cue: 'Different cue' } },
  { ...work, target: { modality: 'hr' as const, low: 140, high: 150, effort_cue: 'Stay relaxed' } },
])('does not group different prescriptions', different => {
  expect(compactWorkout([work, recovery, different])).toHaveLength(3)
  render(<WorkoutStructure structure={[work, recovery, different]} unit="km" />)
  expect(screen.getAllByRole('listitem')).toHaveLength(3)
  expect(screen.queryByText(/×/)).toBeNull()
})
it('keeps pace targets and additional cues', () => {
  render(<WorkoutStructure structure={[{ ...work, target: { modality: 'speed', low: 3, high: 4, effort_cue: 'Keep shoulders loose' } }]} unit="mi" />)
  expect(screen.getByRole('listitem')).toHaveTextContent('Keep shoulders loose')
  expect(screen.getByRole('listitem')).toHaveTextContent('/mi')
})
it('keeps warm-up and cool-down around repeated intervals', () => {
  const groups = compactWorkout([{ ...work, type: 'warmup', duration_value: 720 }, { type: 'repeat', count: 4, steps: [work, recovery] }, work, { ...work, type: 'cooldown', duration_value: 480 }])
  expect(groups.map(group => group.count)).toEqual([1, 5, 1])
})
