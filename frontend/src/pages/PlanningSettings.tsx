import { Button, Card, Disclosure, Input } from '../components/ui'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post, put, qk, invalidateKeys, validDate, pageHref, WEEKDAY_LABELS, type Profile, type CalendarView, type CalendarWriteResult, type StrengthRoutine, type StrengthRoutineSlot, type Unit } from '../api'
import { QueryState } from '../components/QueryState'
import { SyncCard } from '../components/SyncCard'
import { ErrorText, Select, profileBody } from './settings/shared'
import { Goals } from './settings/Goals'
import { Events } from './settings/Events'
import { Anchors } from './settings/Anchors'
import { StrengthSchedule } from './settings/StrengthSchedule'

type SlotDraft = Omit<StrengthRoutineSlot, 'id' | 'version'>
const defaults: SlotDraft[] = [0, 4].map((day, i) => ({
  label: `Full body ${i ? 'B' : 'A'}`,
  default_weekday: day,
  lower_body_cost: 'moderate',
  typical_duration_s: 3600,
  main_lower_body_lifts: [],
  active: true,
}))
const drafts = (routine: StrengthRoutine): SlotDraft[] =>
  routine.slots.length
    ? routine.slots.map((s) => ({
        label: s.label,
        default_weekday: s.default_weekday,
        lower_body_cost: s.lower_body_cost,
        typical_duration_s: s.typical_duration_s,
        main_lower_body_lifts: s.main_lower_body_lifts,
        active: s.active,
      }))
    : defaults
function ScheduleLink() {
  return (
    <a
      href="#settings"
      onClick={(e) => {
        e.preventDefault()
        const el = document.getElementById('strength-schedule') as HTMLDetailsElement | null
        if (el) {
          el.open = true
          el.scrollIntoView({ behavior: 'smooth' })
        }
      }}
    >
      Edit confirmed strength schedule
    </a>
  )
}
function StrengthRoutineEditor({
  slots,
  onChange,
}: {
  slots: SlotDraft[]
  onChange: (slots: SlotDraft[]) => void
}) {
  const change = (i: number, value: Partial<SlotDraft>) =>
    onChange(slots.map((slot, n) => (n === i ? { ...slot, ...value } : slot)))
  return (
    <>
      {slots.map((slot, i) => (
        <fieldset key={i}>
          <legend>Slot {i + 1}</legend>
          <label htmlFor={`slot-${i}-label`}>Label</label>
          <Input
            id={`slot-${i}-label`}
            value={slot.label}
            onChange={(e) => change(i, { label: e.target.value })}
          />
          <Select
            id={`slot-${i}-cost`}
            label="Lower-body cost"
            value={slot.lower_body_cost}
            options={{ low: 'Low', moderate: 'Moderate', high: 'High' }}
            onChange={(v) => change(i, { lower_body_cost: v as SlotDraft['lower_body_cost'] })}
          />
          <label htmlFor={`slot-${i}-duration`}>Typical duration (minutes)</label>
          <Input
            id={`slot-${i}-duration`}
            type="number"
            min={5}
            step={5}
            value={slot.typical_duration_s === null ? '' : slot.typical_duration_s / 60}
            onChange={(e) =>
              change(i, {
                typical_duration_s: e.target.value === '' ? null : Number(e.target.value) * 60,
              })
            }
          />
          <label htmlFor={`slot-${i}-lifts`}>Main lower-body lifts</label>
          <Input
            id={`slot-${i}-lifts`}
            value={slot.main_lower_body_lifts.join(', ')}
            onChange={(e) =>
              change(i, { main_lower_body_lifts: e.target.value.split(',').map((v) => v.trim()) })
            }
          />
          <label htmlFor={`slot-${i}-active`}>
            <input
              id={`slot-${i}-active`}
              type="checkbox"
              checked={slot.active}
              onChange={(e) => change(i, { active: e.target.checked })}
            />
            Active
          </label>
          <Button
            variant="link"
            type="button"
            onClick={() => onChange(slots.filter((_, n) => n !== i))}
          >
            Remove slot
          </Button>
        </fieldset>
      ))}
      <Button
        variant="outline"
        type="button"
        onClick={() =>
          onChange([
            ...slots,
            { ...defaults[0], label: '', typical_duration_s: null, main_lower_body_lifts: [] },
          ])
        }
      >
        Add slot
      </Button>
    </>
  )
}
const cleanSlots = (slots: SlotDraft[]) =>
  slots.map((s) => ({
    ...s,
    label: s.label.trim(),
    main_lower_body_lifts: s.main_lower_body_lifts.map((v) => v.trim()).filter(Boolean),
  }))
function checkSlots(slots: SlotDraft[]) {
  if (slots.some((s) => !s.label.trim())) throw new Error('Each slot needs a label.')
  if (
    slots.some(
      (s) =>
        s.typical_duration_s !== null &&
        (!Number.isFinite(s.typical_duration_s) ||
          s.typical_duration_s <= 0 ||
          s.typical_duration_s % 300 !== 0),
    )
  )
    throw new Error('Use positive durations in five-minute increments.')
}
function Setup({
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
      return post<CalendarWriteResult>('/calendar/bootstrap', {
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
        qk.coach,
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
function Routine({ routine, onSaved }: { routine: StrengthRoutine; onSaved: () => void }) {
  const qc = useQueryClient(),
    [slots, setSlots] = useState(() => drafts(routine))
  const save = useMutation({
    mutationFn: () => {
      checkSlots(slots)
      return put('/strength-routine', {
        expected_version: routine.version,
        slots: cleanSlots(slots),
      })
    },
    onSuccess: () => {
      onSaved()
      invalidateKeys(qc, [qk.strengthRoutine])
    },
  })
  const schedule = routine.schedule
  return (
    <Card>
      <h2>Strength routine</h2>
      <p>
        Two full-body sessions a week are the default commitment. The coach plans runs around these.
      </p>
      <p>
        {schedule.strength_schedule_mode === 'alternating'
          ? `Week A: ${schedule.strength_week_a_days.map((d) => WEEKDAY_LABELS[d]).join(', ')}; Week B: ${schedule.strength_week_b_days.map((d) => WEEKDAY_LABELS[d]).join(', ')}`
          : `Confirmed days: ${schedule.scheduled_strength_days.map((d) => WEEKDAY_LABELS[d]).join(', ')}`}
      </p>
      <ScheduleLink />
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <fieldset disabled={save.isPending}>
          <StrengthRoutineEditor slots={slots} onChange={setSlots} />
          <small>Changes apply to future reviews; existing calendar sessions are not moved.</small>
          {slots.filter((s) => s.active).length !== 2 && (
            <p>
              You have {slots.filter((s) => s.active).length} active slots; the default commitment
              is 2.
            </p>
          )}
          <Button type="submit">Save strength routine</Button>
        </fieldset>
      </form>
      <ErrorText error={save.error} />
    </Card>
  )
}
function ReviewDay({ profile }: { profile: Profile }) {
  const qc = useQueryClient(),
    candidate = profile.preferences.weekly_review_weekday
  const [day, setDay] = useState(
    typeof candidate === 'number' && Number.isInteger(candidate) && candidate >= 0 && candidate <= 6
      ? candidate
      : 6,
  )
  const save = useMutation({
    mutationFn: () =>
      put('/profile', {
        ...profileBody(profile),
        preferences: { ...profile.preferences, weekly_review_weekday: day },
      }),
    onSuccess: () => invalidateKeys(qc, [qk.profile]),
  })
  return (
    <Card>
      <h2>Weekly review day</h2>
      <p>The weekly coach review is suggested on this day.</p>
      <Select
        id="review-weekday"
        label="Review day"
        value={String(day)}
        options={Object.fromEntries(WEEKDAY_LABELS.map((label, i) => [i, label]))}
        onChange={(v) => setDay(Number(v))}
      />
      <Button variant="outline" disabled={save.isPending} onClick={() => save.mutate()}>
        Save review day
      </Button>
      <ErrorText error={save.error} />
      {save.isSuccess && (
        <p className="success-text" role="status">
          Review day saved.
        </p>
      )}
    </Card>
  )
}
function Preferences({
  profile,
  unit,
  setUnit,
}: {
  profile: Profile
  unit: Unit
  setUnit: (u: Unit) => void
}) {
  const qc = useQueryClient(),
    [timezone, setTimezone] = useState(profile.timezone)
  const save = useMutation({
    mutationFn: () => put('/profile', { ...profileBody(profile), timezone: timezone.trim() }),
    onSuccess: () => invalidateKeys(qc, [qk.profile]),
  })
  return (
    <Card>
      <h2>Preferences</h2>
      <div className="field">
        <label htmlFor="timezone">Display timezone</label>
        <Input id="timezone" value={timezone} onChange={(e) => setTimezone(e.target.value)} />
        <small>Use an IANA name, for example America/New_York.</small>
      </div>
      <Button variant="outline" disabled={save.isPending} onClick={() => save.mutate()}>
        Save timezone
      </Button>
      <ErrorText error={save.error} />
      {save.isSuccess && (
        <p className="success-text" role="status">
          Timezone saved.
        </p>
      )}
      <h3>Display units</h3>
      <div className="segmented">
        <Button
          variant="ghost"
          className={
            unit === 'mi' ? 'active bg-card text-foreground shadow-sm' : 'text-muted-foreground'
          }
          onClick={() => setUnit('mi')}
        >
          Miles
        </Button>
        <Button
          variant="ghost"
          className={
            unit === 'km' ? 'active bg-card text-foreground shadow-sm' : 'text-muted-foreground'
          }
          onClick={() => setUnit('km')}
        >
          Kilometers
        </Button>
      </div>
    </Card>
  )
}

export function PlanningSettings({
  unit,
  setUnit,
}: {
  unit: Unit
  setUnit: (unit: Unit) => void
}) {
  const calendar = useQuery({
    queryKey: qk.calendarView('head'),
    queryFn: () => api<CalendarView>('/calendar'),
  })
  const profile = useQuery({ queryKey: qk.profile, queryFn: () => api<Profile>('/profile') })
  const routine = useQuery({
    queryKey: qk.strengthRoutine,
    queryFn: () => api<StrengthRoutine>('/strength-routine'),
  })
  const [routineSaved, setRoutineSaved] = useState(false)
  const [created, setCreated] = useState<number | null>(null),
    view = calendar.data?.data,
    p = profile.data?.data,
    r = routine.data?.data
  return (
    <section className="page-content space-y-5">
      <div className="page-heading">
        <h1>Settings</h1>
        <a href="#guide">User guide</a>
      </div>
      {created !== null && (
        <p className="success-text" role="status">
          Calendar created (version {created}). Open Home to see today.{' '}
          <a href={pageHref.home}>Open Home</a>
        </p>
      )}
      {routineSaved && (
        <p className="success-text" role="status">
          Strength routine saved.
        </p>
      )}
      <SyncCard />
      <QueryState
        loading={calendar.isPending || profile.isPending || routine.isPending}
        error={calendar.error || profile.error || routine.error}
        stale={!!(view && p && r)}
        retry={() => {
          void calendar.refetch()
          void profile.refetch()
          void routine.refetch()
        }}
      >
        {view && p && r && (
          <>
            <div className="grid halves">
              {view.head === 0 ? (
                <Setup
                  key={`${p.version}:${r.version}`}
                  profile={p}
                  routine={r}
                  today={view.today}
                  onCreated={setCreated}
                />
              ) : (
                <Routine key={r.version} routine={r} onSaved={() => setRoutineSaved(true)} />
              )}
              <Disclosure
                variant="card"
                className="training-disclosure"
                id="strength-schedule"
                data-testid="strength-schedule"
              >
                <summary>Strength schedule (weekly or alternating)</summary>
                <StrengthSchedule key={p.version} profile={p} />
              </Disclosure>
              <Preferences key={p.version} profile={p} unit={unit} setUnit={setUnit} />
              <ReviewDay profile={p} />
              <Goals />
              <Events unit={unit} />
            </div>
            <Disclosure
              variant="card"
              className="training-disclosure"
              data-testid="anchors-disclosure"
            >
              <summary>Intensity anchors</summary>
              <Anchors unit={unit} today={view.today} timezone={p.timezone} />
            </Disclosure>
          </>
        )}
      </QueryState>
    </section>
  )
}
