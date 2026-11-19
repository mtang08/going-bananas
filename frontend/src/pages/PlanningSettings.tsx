import { Button, Card, Disclosure, Input } from '../components/ui'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post, put, qk, invalidateKeys, validDate, pageHref, WEEKDAY_LABELS, type Profile, type CalendarView, type CalendarWriteResult, type StrengthRoutine, type Unit } from '../api'
import { QueryState } from '../components/QueryState'
import { SyncCard } from '../components/SyncCard'
import { ErrorText, Select, profileBody } from './settings/shared'
import { Goals } from './settings/Goals'
import { Events } from './settings/Events'
import { Anchors } from './settings/Anchors'
import { StrengthSchedule } from './settings/StrengthSchedule'
import { Routine, StrengthRoutineEditor, ScheduleLink, cleanSlots, checkSlots, drafts } from './settings/strengthRoutine'

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
