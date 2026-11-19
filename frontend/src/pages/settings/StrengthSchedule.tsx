import { Button, Input, NativeSelect } from '../../components/ui'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { put, qk, invalidateKeys, validDate, type Profile } from '../../api'
import { ErrorText, profileBody } from './shared'

const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
function ScheduleDayPicker({
  label,
  days,
  onToggle,
}: {
  label: string
  days: number[]
  onToggle: (day: number) => void
}) {
  return (
    <div className="field">
      <strong>{label}</strong>
      <div className="weekday-picker">
        {weekdayNames.map((name, i) => (
          <label key={name}>
            <input type="checkbox" checked={days.includes(i)} onChange={() => onToggle(i)} />
            {name}
          </label>
        ))}
      </div>
    </div>
  )
}
export function StrengthSchedule({ profile }: { profile: Profile }) {
  const qc = useQueryClient()
  const [anchor, setAnchor] = useState<string | null>(null),
    [confirmAnchor, setConfirmAnchor] = useState<boolean | null>(null),
    [confirmStrength, setConfirmStrength] = useState<boolean | null>(null),
    [strengthDays, setStrengthDays] = useState<number[] | null>(null)
  const [scheduleMode, setScheduleMode] = useState<'weekly' | 'alternating' | null>(null),
    [weekAStart, setWeekAStart] = useState<string | null>(null),
    [weekADays, setWeekADays] = useState<number[] | null>(null),
    [weekBDays, setWeekBDays] = useState<number[] | null>(null)
  const [mobilityADays, setMobilityADays] = useState<number[] | null>(null),
    [mobilityBDays, setMobilityBDays] = useState<number[] | null>(null),
    [optionalMobilityDays, setOptionalMobilityDays] = useState<number[] | null>(null)
  const p = profile
  const chosenAnchor = anchor ?? p.cycle_anchor ?? ''
  const days = strengthDays ?? p.scheduled_strength_days ?? []
  const mode = scheduleMode ?? p.strength_schedule_mode ?? 'weekly'
  const aDays = weekADays ?? p.strength_week_a_days ?? [],
    bDays = weekBDays ?? p.strength_week_b_days ?? []
  const mobilityA = mobilityADays ?? p.mobility_week_a_days ?? [],
    mobilityB = mobilityBDays ?? p.mobility_week_b_days ?? [],
    optionalMobility = optionalMobilityDays ?? p.mobility_optional_days ?? []
  const chosenWeekAStart = weekAStart ?? p.strength_week_a_start ?? ''
  const confirmedStrength = confirmStrength ?? p.strength_days_confirmed ?? false
  const scheduleError =
    confirmedStrength &&
    (mode === 'weekly'
      ? days.length !== 2
      : aDays.length !== 2 ||
        bDays.length !== 2 ||
        !validDate(chosenWeekAStart) ||
        new Date(`${chosenWeekAStart}T12:00:00Z`).getUTCDay() !== 1)
  const toggleDay = (value: number, items: number[], set: (value: number[]) => void) => {
    set(
      items.includes(value)
        ? items.filter((day) => day !== value)
        : [...items, value].sort((a, b) => a - b),
    )
    setConfirmStrength(false)
  }
  const save = useMutation({
    mutationFn: () =>
      put('/profile', {
        ...profileBody(profile),
        cycle_anchor: anchor === null ? profile.cycle_anchor : anchor || null,
        anchor_confirmed: confirmAnchor ?? profile.anchor_confirmed,
        strength_days_confirmed: confirmedStrength,
        scheduled_strength_days: days,
        strength_schedule_mode: mode,
        strength_week_a_start: chosenWeekAStart || null,
        strength_week_a_days: aDays,
        strength_week_b_days: bDays,
        mobility_week_a_days: mobilityA,
        mobility_week_b_days: mobilityB,
        mobility_optional_days: optionalMobility,
      }),
    onSuccess: () => invalidateKeys(qc, [qk.profile, qk.strengthRoutine, qk.coach]),
  })
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <div className="field">
        <label htmlFor="anchor">Run parity anchor</label>
        <Input
          id="anchor"
          type="date"
          value={chosenAnchor}
          onChange={(e) => {
            setAnchor(e.target.value)
            setConfirmAnchor(false)
          }}
        />
        <small>
          One confirmed run opportunity date sets every-other-day parity. It is independent of Week
          A/B strength.
        </small>
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={confirmAnchor ?? p.anchor_confirmed}
          onChange={(e) => setConfirmAnchor(e.target.checked)}
        />{' '}
        I confirm this run anchor date
      </label>
      <div className="field">
        <label htmlFor="schedule-mode">Strength schedule</label>
        <NativeSelect
          id="schedule-mode"
          value={mode}
          onChange={(e) => {
            setScheduleMode(e.target.value as 'weekly' | 'alternating')
            setConfirmStrength(false)
          }}
        >
          <option value="weekly">Same two days every week</option>
          <option value="alternating">Alternating Week A / Week B</option>
        </NativeSelect>
        <small>
          Choose two full-body strength days in each week. The pattern repeats automatically; no
          weekly plan draft is needed.
        </small>
      </div>
      {mode === 'weekly' ? (
        <ScheduleDayPicker
          label="Full-body strength · every week"
          days={days}
          onToggle={(day) => toggleDay(day, days, setStrengthDays)}
        />
      ) : (
        <>
          <div className="field">
            <label htmlFor="week-a-start">Week A Monday</label>
            <Input
              id="week-a-start"
              type="date"
              value={chosenWeekAStart}
              onChange={(e) => {
                setWeekAStart(e.target.value)
                setConfirmStrength(false)
              }}
            />
            <small>
              These seven dates use Week A, the next seven use Week B, then the 14-day pattern
              repeats.
            </small>
          </div>
          <div className="schedule-week">
            <h3>Week A</h3>
            <p>Starting on the reference Monday.</p>
            <ScheduleDayPicker
              label="Full-body strength · two days"
              days={aDays}
              onToggle={(day) => toggleDay(day, aDays, setWeekADays)}
            />
            <ScheduleDayPicker
              label="Required gym mobility"
              days={mobilityA}
              onToggle={(day) => toggleDay(day, mobilityA, setMobilityADays)}
            />
          </div>
          <div className="schedule-week">
            <h3>Week B</h3>
            <p>The following Monday through Sunday.</p>
            <ScheduleDayPicker
              label="Full-body strength · two days"
              days={bDays}
              onToggle={(day) => toggleDay(day, bDays, setWeekBDays)}
            />
            <ScheduleDayPicker
              label="Required gym mobility"
              days={mobilityB}
              onToggle={(day) => toggleDay(day, mobilityB, setMobilityBDays)}
            />
          </div>
          <ScheduleDayPicker
            label="Optional mobility · both weeks"
            days={optionalMobility}
            onToggle={(day) => toggleDay(day, optionalMobility, setOptionalMobilityDays)}
          />
        </>
      )}
      <label className="checkbox">
        <input
          type="checkbox"
          checked={confirmedStrength}
          onChange={(e) => setConfirmStrength(e.target.checked)}
        />{' '}
        I confirm this repeating strength and mobility pattern
      </label>
      {scheduleError && (
        <p className="error-text" role="alert">
          Choose exactly two full-body strength days per week
          {mode === 'alternating' ? ' and a valid Week A Monday' : ''} before confirming.
        </p>
      )}
      <ErrorText error={save.error} />
      {save.isSuccess && (
        <p className="success-text" role="status">
          Strength schedule saved as a new profile version.
        </p>
      )}
      <Button type="submit" disabled={save.isPending || scheduleError}>
        Save strength schedule
      </Button>
    </form>
  )
}
