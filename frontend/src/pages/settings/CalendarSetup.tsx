import { Button, Card, Input } from '../../components/ui'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { bootstrapCalendar, put } from '../../api/client'
import { qk, invalidateKeys } from '../../api/queryKeys'
import { validDate } from '../../lib/format'
import type { Profile } from '../../api/types/profile'
import type { StrengthRoutine } from '../../api/types/blocks'
import { ErrorText, profileBody } from './shared'
import {
  StrengthRoutineEditor,
  ScheduleLink,
  cleanSlots,
  checkSlots,
  drafts,
} from './strengthRoutine'

export function CalendarSetup({
  profile,
  routine,
  today,
  onCreated,
}: {
  profile: Profile
  routine: StrengthRoutine
  today: string
  onCreated: (version: number) => void
}) {
  const qc = useQueryClient(),
    [anchor, setAnchor] = useState(profile.cycle_anchor ?? ''),
    [confirmed, setConfirmed] = useState(false)
  const [timezone, setTimezone] = useState(profile.timezone),
    [slots, setSlots] = useState(() => drafts(routine))
  const save = useMutation({
    mutationFn: async () => {
      checkSlots(slots)
      await put('/profile', {
        ...profileBody(profile),
        timezone,
        cycle_anchor: anchor,
        anchor_confirmed: true,
      })
      await put('/strength-routine', {
        expected_version: routine.version,
        slots: cleanSlots(slots),
      })
      return bootstrapCalendar({
        anchor_date: anchor,
        pattern: { quality: 1, long: 1 },
        start_date: today,
      })
    },
    onSuccess: (response) => {
      onCreated(response.data.version)
      invalidateKeys(qc, [
        qk.calendar,
        qk.metrics,
        qk.prompts,
        qk.proposals,
        qk.profile,
        qk.strengthRoutine,
      ])
    },
    onError: () => invalidateKeys(qc, [qk.profile, qk.strengthRoutine]),
  })
  return (
    <Card data-testid="setup-wizard">
      <h2>Set up your plan</h2>
      <p>Confirm these once. The app then fills the next 14 days; no coach is needed.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <fieldset disabled={save.isPending}>
          <fieldset>
            <legend>1. Run-cycle anchor</legend>
            <label htmlFor="setup-anchor">First run day of the cycle</label>
            <Input
              type="date"
              id="setup-anchor"
              value={anchor}
              onChange={(e) => setAnchor(e.target.value)}
            />
            <label htmlFor="setup-anchor-confirm">
              <input
                type="checkbox"
                id="setup-anchor-confirm"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              I confirm runs fall every other day from this date.
            </label>
          </fieldset>
          <fieldset>
            <legend>2. Strength routine</legend>
            {routine.suggested && (
              <div className="notice muted">
                Pre-filled from your Strong history. Check each slot.
              </div>
            )}
            <StrengthRoutineEditor slots={slots} onChange={setSlots} />
          </fieldset>
          <fieldset>
            <legend>3. Weekly pattern</legend>
            <p>1 quality session, 1 long run, the rest easy.</p>
            <ScheduleLink />
            {!profile.strength_days_confirmed && (
              <p>Confirm the strength schedule before creating a calendar.</p>
            )}
          </fieldset>
          <fieldset>
            <legend>4. Timezone</legend>
            <label htmlFor="setup-timezone">Timezone</label>
            <Input
              id="setup-timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
            />
            <small>IANA name, for example America/New_York.</small>
          </fieldset>
          <p className="fineprint">Goals and events are optional; add them in the panels below.</p>
          <Button
            type="submit"
            disabled={!validDate(anchor) || !confirmed || !profile.strength_days_confirmed}
          >
            Create my 14-day calendar
          </Button>
        </fieldset>
      </form>
      <ErrorText error={save.error} />
    </Card>
  )
}
