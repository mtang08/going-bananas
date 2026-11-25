import type { StrengthRoutineSlot } from '../../api/types/blocks'
import type { SessionState } from '../../api/types/calendar'
import type { ProposalChange, ProposalSession } from '../../api/types/coach'
import { mondayOfWeek } from '../../components/PlanOverview'
import { addDays } from '../../lib/format'
import { readStructure } from './helpers'

export const NEARBY_DAYS = 3

export function firstImpactWeek(changes: ProposalChange[]): string | null {
  const dates = changes.flatMap(({ before, after }) =>
    [before?.local_date, after?.local_date].filter((day): day is string => Boolean(day)),
  )
  return dates.length ? mondayOfWeek(dates.sort()[0]) : null
}

type Dose = { known: number; incomplete: boolean }
type Prescription = { distance: number | null; duration: number | null }
type ImpactChange = {
  change: ProposalChange
  key: string
  before: ProposalSession | null
  after: ProposalSession | null
}

function runDose(session: ProposalSession): Prescription {
  if (session.kind !== 'run') return { distance: 0, duration: 0 }
  const { steps } = readStructure(session)
  const total = (unit: 'distance' | 'time') =>
    steps.length && steps.every((step) => step.duration_type === unit)
      ? steps.reduce((sum, step) => sum + step.duration_value, 0)
      : null
  return {
    distance: session.planned_distance_m ?? total('distance'),
    duration: session.planned_duration_s ?? total('time'),
  }
}

function doseDelta(
  changes: ImpactChange[],
  start: string,
  end: string,
  field: keyof Prescription,
): Dose {
  const amount = (session: ProposalSession | null) =>
    session?.local_date && session.local_date >= start && session.local_date <= end
      ? runDose(session)[field]
      : 0
  let known = 0
  let incomplete = false
  for (const { before, after } of changes) {
    const from = amount(before)
    const to = amount(after)
    // A dose-preserving move within one week does not change that week's volume.
    if (
      from === null &&
      to === null &&
      before?.kind === after?.kind &&
      before?.planned_duration_s === after?.planned_duration_s &&
      before?.planned_distance_m === after?.planned_distance_m &&
      JSON.stringify(before?.structure ?? null) === JSON.stringify(after?.structure ?? null)
    )
      continue
    known += (to ?? 0) - (from ?? 0)
    incomplete ||= from === null || to === null
  }
  return { known, incomplete }
}

const DEMANDING_RUNS = new Set([
  'REC002',
  'REC003',
  'REC004',
  'REC005',
  'REC006',
  'REC008',
  'REC009',
])
const daysFrom = (from: string, to: string) =>
  (Date.parse(`${to}T12:00:00Z`) - Date.parse(`${from}T12:00:00Z`)) / 86400000

export function scheduleImpact(
  accepted: SessionState[],
  changes: ProposalChange[],
  selected: ReadonlySet<string>,
  start: string,
  strengthSlots: StrengthRoutineSlot[],
) {
  const schedule = new Map(
    accepted.filter((s) => !s.deleted).map((s) => [s.session_uid, s as ProposalSession]),
  )
  const selectedChanges = changes
    .filter((change) => change.decision === 'pending' && selected.has(change.change_id))
    .map((change): ImpactChange => {
      const key = change.session_uid ?? `addition-${change.change_id}`
      const original = schedule.get(key)
      const before = change.op === 'add' ? null : (original ?? change.before)
      const after = change.op === 'delete' ? null : { ...before, ...change.after }
      return { change, key, before, after }
    })
  for (const { key, after } of selectedChanges) {
    if (after) schedule.set(key, after)
    else schedule.delete(key)
  }
  const highCost = new Set(
    strengthSlots.filter((s) => s.lower_body_cost === 'high').map((s) => s.id),
  )
  const near = (key: string, date: string) =>
    [...schedule.entries()]
      .flatMap(([uid, session]) => {
        if (
          uid === key ||
          !session.local_date ||
          session.placeholder ||
          (session.kind !== 'run' && session.kind !== 'strength')
        )
          return []
        const difference = daysFrom(date, session.local_date)
        const demanding =
          (session.brief?.effort.rpe_low ?? 0) >= 6 ||
          (session.kind === 'run' && DEMANDING_RUNS.has(session.recipe_id ?? '')) ||
          (session.kind === 'strength' &&
            !!session.strength_slot_id &&
            highCost.has(session.strength_slot_id))
        return Math.abs(difference) <= NEARBY_DAYS && demanding ? [{ session, difference }] : []
      })
      .sort(
        (a, b) => Math.abs(a.difference) - Math.abs(b.difference) || a.difference - b.difference,
      )[0]

  const last = addDays(start, 13)
  const inside = (day?: string) => !!day && start <= day && day <= last
  const impact = selectedChanges.map((row) => {
    const from = row.before?.local_date
    const to = row.after?.local_date
    const touchesWeeks = inside(from) || inside(to)
    return {
      ...row,
      touchesWeeks,
      crossesWindow: touchesWeeks && ((!!from && !inside(from)) || (!!to && !inside(to))),
      nearby:
        touchesWeeks && inside(to) && to && from && to !== from && row.after?.kind === 'run'
          ? near(row.key, to)
          : undefined,
      movedRun:
        touchesWeeks && inside(to) && !!to && !!from && to !== from && row.after?.kind === 'run',
    }
  })
  return {
    changes: impact,
    weeks: [start, addDays(start, 7)].map((first) => {
      const end = addDays(first, 6)
      return {
        start: first,
        end,
        distance: doseDelta(selectedChanges, first, end, 'distance'),
        duration: doseDelta(selectedChanges, first, end, 'duration'),
      }
    }),
  }
}
