import { describe, expect, it } from 'vitest'
import { mondayOfWeek } from '../src/components/PlanOverview'
describe('athlete calendar week', () => {
  it('keeps Sunday in the week ending today', () => {
    expect(mondayOfWeek('2026-11-15')).toBe('2026-11-09')
  })
  it('starts a new week on Monday independent of browser time', () => {
    expect(mondayOfWeek('2026-11-16')).toBe('2026-11-16')
  })
})
