import { addDays, dateLabel, fmtDistance, fmtDuration, type Unit } from '../lib/format'
import { formatStep } from '../lib/structure'
import { sessionTitle } from '../lib/session'
import type { PlannedStep, SessionState } from '../api/types/calendar'

function effortText(effort: { rpe_low: number; rpe_high: number; feel: string }): string {
  const range =
    effort.rpe_low === effort.rpe_high
      ? `${effort.rpe_low}`
      : `${effort.rpe_low}–${effort.rpe_high}`
  return `RPE ${range} (${effort.feel})`
}

export function weeklyWorkoutText(sessions: SessionState[], monday: string, unit: Unit): string {
  const sunday = addDays(monday, 6)
  const lines = [`Workouts: ${monday} to ${sunday}`, '']
  const format = (step: PlannedStep) => {
    const text = formatStep(step, unit)
    const cue = step.target?.modality !== 'effort' ? step.target?.effort_cue?.trim() : null
    return cue ? `${text} · ${cue}` : text
  }
  for (let i = 0; i < 7; i++) {
    const day = addDays(monday, i)
    lines.push(`${dateLabel(day, { weekday: 'long', month: 'short', day: 'numeric' })} (${day})`)
    const planned = sessions
      .filter((s) => !s.deleted && s.local_date === day)
      .sort((a, b) => a.slot - b.slot)
    if (!planned.length) lines.push('  No planned session')
    for (const session of planned) {
      const title =
        session.legacy_unstructured && session.kind === 'run'
          ? 'Imported run'
          : session.custom && !session.recipe_id
            ? session.intent
            : sessionTitle(session)
      lines.push(`  ${title} (${session.certainty})`)
      const amounts = [
        session.planned_duration_s == null ? null : fmtDuration(session.planned_duration_s),
        session.planned_distance_m == null ? null : fmtDistance(session.planned_distance_m, unit),
      ].filter(Boolean)
      if (amounts.length) lines.push(`    ${amounts.join(' · ')}`)
      if (session.intent && session.intent !== title) lines.push(`    ${session.intent}`)
      for (const item of session.structure ?? []) {
        if (item.type === 'repeat') {
          lines.push(`    ${item.count} ×`)
          for (const step of item.steps) lines.push(`      ${format(step)}`)
        } else lines.push(`    ${format(item)}`)
      }
      if (session.brief) {
        lines.push(`    Effort: ${effortText(session.brief.effort)}`)
        for (const rule of session.brief.adjust_if)
          lines.push(`    Adjust if: ${rule.when} → ${rule.then}`)
      }
      if (session.notes?.trim()) lines.push(`    Notes: ${session.notes.trim()}`)
    }
    lines.push('')
  }
  return lines.join('\n')
}

export function downloadWeeklyWorkouts(sessions: SessionState[], monday: string, unit: Unit): void {
  const blob = new Blob([weeklyWorkoutText(sessions, monday, unit)], {
    type: 'text/plain;charset=utf-8',
  })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `workouts-${monday}.txt`
  link.click()
  URL.revokeObjectURL(url)
}
