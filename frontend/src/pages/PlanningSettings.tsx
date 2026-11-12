import { Button, Card, Input, NativeSelect } from '../components/ui'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  post,
  put,
  patch,
  qk,
  invalidateKeys,
  ApiError,
  validDate,
  dateLabel,
  fmtDistance,
  fmtClock,
  fmtPaceFromSpeed,
  clockToSeconds,
  paceToSpeed,
  pageHref,
  WEEKDAY_LABELS,
  HORIZON_LABELS,
  EVENT_PRIORITY_LABELS,
  ANCHOR_KIND_LABELS,
  ANCHOR_UNIT,
  PROTOCOL_LABELS,
  type Profile,
  type CalendarView,
  type CalendarWriteResult,
  type StrengthRoutine,
  type StrengthRoutineSlot,
  type Goal,
  type GoalHorizon,
  type RaceEvent,
  type EventPriority,
  type EventStatus,
  type AnchorList,
  type AnchorKind,
  type AnchorProtocol,
  type AnchorConfidence,
  type Unit,
  type CheckinRequest,
} from '../api'
import { QueryState } from '../components/QueryState'
import { Settings } from './Settings'

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
function profileBody(profile: Profile) {
  const keys = [
    'timezone',
    'cycle_anchor',
    'anchor_confirmed',
    'strength_days_confirmed',
    'scheduled_strength_days',
    'strength_schedule_mode',
    'strength_week_a_start',
    'strength_week_a_days',
    'strength_week_b_days',
    'mobility_week_a_days',
    'mobility_week_b_days',
    'mobility_optional_days',
    'facts',
    'preferences',
    'unknowns',
  ] as const
  return {
    ...Object.fromEntries(keys.map((key) => [key, profile[key]])),
    expected_version: profile.version,
  }
}
function ErrorText({ error }: { error: Error | null }) {
  if (!error) return null
  const message =
    error instanceof ApiError && error.code === 'version_conflict'
      ? 'Settings changed in another tab. Reload and try again.'
      : error instanceof ApiError && error.code === 'calendar_exists'
        ? 'A calendar already exists. Edit it on the Calendar page.'
        : error.message
  return (
    <p className="error-text" role="alert">
      {message}
    </p>
  )
}
function Select({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string
  label: string
  value: string
  options: Record<string, string>
  onChange: (value: string) => void
}) {
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <NativeSelect id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {Object.entries(options).map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </NativeSelect>
    </>
  )
}
function ScheduleLink() {
  return (
    <a
      href="#settings"
      onClick={(e) => {
        e.preventDefault()
        document.getElementById('existing-settings')?.scrollIntoView({ behavior: 'smooth' })
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
function Goals() {
  const qc = useQueryClient(),
    query = useQuery({ queryKey: qk.goals, queryFn: () => api<{ items: Goal[] }>('/goals') })
  const [editing, setEditing] = useState<Goal | null>(null),
    [text, setText] = useState(''),
    [horizon, setHorizon] = useState<GoalHorizon>('3_6_months'),
    [priority, setPriority] = useState(1),
    [status, setStatus] = useState<Goal['status']>('active')
  const reset = () => {
    setEditing(null)
    setText('')
    setHorizon('3_6_months')
    setPriority(1)
    setStatus('active')
  }
  const save = useMutation({
    mutationFn: () =>
      editing
        ? patch(`/goals/${encodeURIComponent(editing.id)}`, {
            expected_version: editing.version,
            text: text.trim(),
            horizon,
            priority,
            status,
          })
        : post('/goals', { text: text.trim(), horizon, priority }),
    onSuccess: () => {
      invalidateKeys(qc, [qk.goals, qk.coach])
      reset()
    },
  })
  return (
    <Card>
      <h2>Goals</h2>
      <QueryState
        loading={query.isPending}
        error={query.error}
        stale={!!query.data}
        retry={() => {
          void query.refetch()
        }}
      >
        {!query.data?.data.items.length && <p>No goals yet.</p>}
        {query.data?.data.items.map((g) => (
          <div key={g.id}>
            {g.text} · {HORIZON_LABELS[g.horizon]} · priority {g.priority} · {g.status}{' '}
            <Button
              variant="link"
              onClick={() => {
                setEditing(g)
                setText(g.text)
                setHorizon(g.horizon)
                setPriority(g.priority)
                setStatus(g.status)
                save.reset()
              }}
            >
              Edit
            </Button>
          </div>
        ))}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <fieldset disabled={save.isPending}>
            <label htmlFor="goal-text">Goal</label>
            <Input
              id="goal-text"
              required
              maxLength={200}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
            <Select
              id="goal-horizon"
              label="Horizon"
              value={horizon}
              options={HORIZON_LABELS}
              onChange={(v) => setHorizon(v as GoalHorizon)}
            />
            <Select
              id="goal-priority"
              label="Priority (1 = highest)"
              value={String(priority)}
              options={Object.fromEntries([1, 2, 3, 4, 5].map((n) => [n, String(n)]))}
              onChange={(v) => setPriority(Number(v))}
            />
            {editing && (
              <Select
                id="goal-status"
                label="Status"
                value={status}
                options={{ active: 'Active', paused: 'Paused', done: 'Done', dropped: 'Dropped' }}
                onChange={(v) => setStatus(v as Goal['status'])}
              />
            )}
            <Button type="submit">{editing ? 'Save goal' : 'Add goal'}</Button>
            {editing && (
              <Button variant="link" type="button" onClick={reset}>
                Cancel
              </Button>
            )}
          </fieldset>
        </form>
        <ErrorText error={save.error} />
        {save.isSuccess && (
          <p className="success-text" role="status">
            Goal saved.
          </p>
        )}
      </QueryState>
    </Card>
  )
}
const RACE_DISTANCES: Record<string, string> = {
  '1609.344': '1 mile',
  '5000': '5K',
  '8000': '8K',
  '10000': '10K',
  '15000': '15K',
  '16093.44': '10 miles',
  '21097.5': 'Half marathon',
  '42195': 'Marathon',
}
function Events({ unit }: { unit: Unit }) {
  const qc = useQueryClient(),
    query = useQuery({ queryKey: qk.events, queryFn: () => api<{ items: RaceEvent[] }>('/events') })
  const [editing, setEditing] = useState<RaceEvent | null>(null),
    [name, setName] = useState(''),
    [day, setDay] = useState(''),
    [distance, setDistance] = useState(''),
    [distanceEdited, setDistanceEdited] = useState(false)
  const [priority, setPriority] = useState<EventPriority>('optional'),
    [status, setStatus] = useState<EventStatus>('planned'),
    [result, setResult] = useState(''),
    [resultEdited, setResultEdited] = useState(false)
  const reset = () => {
    setEditing(null)
    setName('')
    setDay('')
    setDistance('')
    setDistanceEdited(false)
    setResult('')
    setResultEdited(false)
    setPriority('optional')
    setStatus('planned')
  }
  const save = useMutation({
    mutationFn: () => {
      const result_s =
        status !== 'completed'
          ? null
          : editing && !resultEdited
            ? editing.result_s
            : clockToSeconds(result)
      if (status === 'completed' && result.trim() && result_s === null)
        throw new Error('Enter the result as h:mm:ss or m:ss.')
      const distance_m =
        editing && !distanceEdited
          ? editing.distance_m
          : distance === ''
            ? null
            : Number(distance)
      if (distance_m !== null && (!Number.isFinite(distance_m) || distance_m <= 0))
        throw new Error('Enter a positive distance.')
      const body = { name: name.trim(), event_date: day, distance_m, priority, status, result_s }
      return editing
        ? patch(`/events/${encodeURIComponent(editing.id)}`, {
            expected_version: editing.version,
            ...body,
          })
        : post('/events', body)
    },
    onSuccess: () => {
      invalidateKeys(qc, [qk.events, qk.coach])
      reset()
    },
  })
  return (
    <Card>
      <h2>Events</h2>
      <p>Events feed the next coach review; the calendar does not change automatically.</p>
      <QueryState
        loading={query.isPending}
        error={query.error}
        stale={!!query.data}
        retry={() => {
          void query.refetch()
        }}
      >
        {!query.data?.data.items.length && <p>No events yet.</p>}
        {query.data?.data.items.map((event) => (
          <div key={event.id}>
            {event.name} ·{' '}
            {dateLabel(event.event_date, { month: 'short', day: 'numeric', year: 'numeric' })} ·{' '}
            {event.distance_m === null ? 'distance not set' : fmtDistance(event.distance_m, unit)} ·{' '}
            {EVENT_PRIORITY_LABELS[event.priority]} · {event.status}
            {event.result_s !== null && ` · result ${fmtClock(event.result_s)}`}{' '}
            <Button
              variant="link"
              onClick={() => {
                setEditing(event)
                setName(event.name)
                setDay(event.event_date)
                setDistance(event.distance_m === null ? '' : String(event.distance_m))
                setDistanceEdited(false)
                setPriority(event.priority)
                setStatus(event.status)
                setResult(event.result_s === null ? '' : fmtClock(event.result_s))
                setResultEdited(false)
                save.reset()
              }}
            >
              Edit
            </Button>
          </div>
        ))}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <fieldset disabled={save.isPending}>
            <label htmlFor="event-name">Event</label>
            <Input
              id="event-name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <label htmlFor="event-date">Date</label>
            <Input
              id="event-date"
              type="date"
              required
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
            <label htmlFor="event-distance">Distance</label>
            <NativeSelect
              id="event-distance"
              value={distance}
              onChange={(e) => {
                setDistance(e.target.value)
                setDistanceEdited(true)
              }}
            >
              <option value="">Distance not set</option>
              {Object.entries(RACE_DISTANCES)
                .sort(([a], [b]) => Number(a) - Number(b))
                .map(([meters, label]) => (
                  <option key={meters} value={meters}>{label}</option>
                ))}
              {editing?.distance_m != null && !RACE_DISTANCES[String(editing.distance_m)] && (
                <option value={String(editing.distance_m)}>
                  Existing distance ({fmtDistance(editing.distance_m, unit)})
                </option>
              )}
            </NativeSelect>
            <Select
              id="event-priority"
              label="Priority"
              value={priority}
              options={EVENT_PRIORITY_LABELS}
              onChange={(v) => setPriority(v as EventPriority)}
            />
            <Select
              id="event-status"
              label="Status"
              value={status}
              options={{
                planned: 'Planned',
                registered: 'Registered',
                completed: 'Completed',
                cancelled: 'Cancelled',
              }}
              onChange={(v) => setStatus(v as EventStatus)}
            />
            {status === 'completed' && (
              <>
                <label htmlFor="event-result">Result (h:mm:ss or m:ss)</label>
                <Input
                  id="event-result"
                  value={result}
                  onChange={(e) => {
                    setResult(e.target.value)
                    setResultEdited(true)
                  }}
                />
              </>
            )}
            <Button type="submit">{editing ? 'Save event' : 'Add event'}</Button>
            {editing && (
              <Button variant="link" type="button" onClick={reset}>
                Cancel
              </Button>
            )}
          </fieldset>
        </form>
        <ErrorText error={save.error} />
        {save.isSuccess && (
          <p className="success-text" role="status">
            Event saved.
          </p>
        )}
      </QueryState>
    </Card>
  )
}
function localNoon(day: string, timezone: string): string {
  if (!validDate(day)) throw new Error('Choose a valid calibration date.')
  const desired = Date.parse(`${day}T12:00:00Z`)
  let candidate = desired
  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
  })
  for (let n = 0; n < 2; n++) {
    const parts = Object.fromEntries(
      formatter.formatToParts(candidate).map((part) => [part.type, part.value]),
    )
    const wall = Date.parse(
      `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}Z`,
    )
    candidate += desired - wall
  }
  return new Date(candidate).toISOString()
}
function Anchors({ unit, today, timezone }: { unit: Unit; today: string; timezone: string }) {
  const qc = useQueryClient(),
    query = useQuery({ queryKey: qk.anchors, queryFn: () => api<AnchorList>('/anchors') })
  const [kind, setKind] = useState<AnchorKind>('hr_aerobic_upper'),
    [value, setValue] = useState(''),
    [protocol, setProtocol] = useState<AnchorProtocol>('manual'),
    [confidence, setConfidence] = useState<AnchorConfidence>('moderate')
  const [day, setDay] = useState(today),
    [conditions, setConditions] = useState(''),
    [notes, setNotes] = useState('')
  const units = ANCHOR_UNIT[kind],
    items = query.data?.data.items ?? []
  const save = useMutation({
    mutationFn: () => {
      const value_low =
        units === 'mps'
          ? paceToSpeed(value, unit)
          : units === 's'
            ? clockToSeconds(value)
            : value.trim()
              ? Number(value)
              : null
      if (
        units === 'bpm' &&
        (value_low === null || !Number.isInteger(value_low) || value_low < 30 || value_low > 230)
      )
        throw new Error('Enter a heart rate between 30 and 230 bpm.')
      if (units === 'm' && (value_low === null || !Number.isFinite(value_low) || value_low <= 0))
        throw new Error('Enter a positive distance in metres.')
      if (units === 'mps' && value_low === null) throw new Error('Enter pace as m:ss.')
      if (units === 's' && (value_low === null || value_low <= 0))
        throw new Error('Enter time as h:mm:ss or m:ss.')
      const replaced = new Set(items.map((a) => a.supersedes_key))
      const predecessor = items
        .filter((a) => a.kind === kind && !replaced.has(a.anchor_key))
        .sort(
          (a, b) =>
            b.valid_from.localeCompare(a.valid_from) ||
            b.calibrated_at.localeCompare(a.calibrated_at),
        )[0]
      return post('/anchors', {
        kind,
        value_low,
        value_high: null,
        unit: units,
        protocol,
        confidence,
        calibrated_at: localNoon(day, timezone),
        valid_from: day,
        conditions: conditions.trim() || null,
        notes: notes.trim() || null,
        supersedes_key: predecessor?.anchor_key ?? null,
      })
    },
    onSuccess: () => {
      invalidateKeys(qc, [qk.anchors, qk.metrics, qk.coach])
      setValue('')
    },
  })
  return (
    <Card>
      <h2>Intensity anchors</h2>
      <div className="notice muted">
        The app never converts a race time into zones. Zones use the aerobic-upper and
        threshold-lower anchors you enter. Intensity metrics stay not assessable until both anchors
        of a modality exist.
      </div>
      <QueryState
        loading={query.isPending}
        error={query.error}
        stale={!!query.data}
        retry={() => {
          void query.refetch()
        }}
      >
        {!items.length && <p>No anchors yet. Intensity metrics are not assessable.</p>}
        {[...items]
          .sort((a, b) => b.calibrated_at.localeCompare(a.calibrated_at))
          .map((a) => (
            <p data-testid="anchor-row" key={a.anchor_key}>
              {ANCHOR_KIND_LABELS[a.kind]} ·{' '}
              {a.unit === 'bpm'
                ? `${a.value_low}${a.value_high !== null ? `–${a.value_high}` : ''} bpm`
                : a.unit === 'mps'
                  ? fmtPaceFromSpeed(a.value_low, unit)
                  : a.unit === 's'
                    ? fmtClock(a.value_low)
                    : `${a.value_low} m`}{' '}
              · {PROTOCOL_LABELS[a.protocol]} · {a.confidence} confidence · {a.status} · calibrated{' '}
              {dateLabel(a.valid_from)}
              {a.status === 'active' && a.review_after < today && ' · Review due'}
            </p>
          ))}
        <form
          onSubmit={(e) => {
            e.preventDefault()
            save.mutate()
          }}
        >
          <fieldset disabled={save.isPending}>
            <Select
              id="anchor-kind"
              label="Anchor"
              value={kind}
              options={ANCHOR_KIND_LABELS}
              onChange={(v) => {
                setKind(v as AnchorKind)
                setValue('')
              }}
            />
            <label htmlFor="anchor-value">
              {units === 'bpm'
                ? 'Heart rate (bpm)'
                : units === 'mps'
                  ? `Pace (m:ss per ${unit})`
                  : units === 's'
                    ? 'Time (h:mm:ss or m:ss)'
                    : 'Distance (metres)'}
            </label>
            <Input id="anchor-value" value={value} onChange={(e) => setValue(e.target.value)} />
            <Select
              id="anchor-protocol"
              label="Method"
              value={protocol}
              options={PROTOCOL_LABELS}
              onChange={(v) => setProtocol(v as AnchorProtocol)}
            />
            <Select
              id="anchor-confidence"
              label="Confidence"
              value={confidence}
              options={{
                high: 'High',
                moderate: 'Moderate',
                low: 'Low',
                insufficient: 'Insufficient',
              }}
              onChange={(v) => setConfidence(v as AnchorConfidence)}
            />
            <label htmlFor="anchor-date">Calibrated on</label>
            <Input
              id="anchor-date"
              type="date"
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
            <label htmlFor="anchor-conditions">Conditions (optional)</label>
            <Input
              id="anchor-conditions"
              value={conditions}
              onChange={(e) => setConditions(e.target.value)}
            />
            <label htmlFor="anchor-notes">Notes (optional)</label>
            <Input id="anchor-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <Button type="submit">Save anchor</Button>
          </fieldset>
        </form>
        <ErrorText error={save.error} />
        {save.isSuccess && (
          <p className="success-text" role="status">
            Anchor saved. Intensity metrics recalculate in the background.
          </p>
        )}
      </QueryState>
    </Card>
  )
}
export function PlanningSettings({
  unit,
  setUnit,
  onCheckin,
}: {
  unit: Unit
  setUnit: (unit: Unit) => void
  onCheckin: (request: CheckinRequest) => void
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
    <>
      <section className="page-content">
        <div className="page-heading">
          <h1>Planning settings</h1>
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
                <>
                  <Card data-testid="setup-done">
                    <h2>Plan setup</h2>
                    <p>
                      Calendar created. Current version {view.head}. Change sessions on the Calendar
                      page.
                    </p>
                    <a href={pageHref.calendar}>Open calendar</a>
                  </Card>
                  <Routine key={r.version} routine={r} onSaved={() => setRoutineSaved(true)} />
                </>
              )}
              <ReviewDay profile={p} />
              <Goals />
              <Events unit={unit} />
              <Anchors unit={unit} today={view.today} timezone={p.timezone} />
            </div>
          )}
        </QueryState>
      </section>
      <div id="existing-settings">
        <Settings
          unit={unit}
          setUnit={setUnit}
          onCheckin={() => onCheckin({ kind: 'exception', prompt: null, activityId: null })}
        />
      </div>
    </>
  )
}
