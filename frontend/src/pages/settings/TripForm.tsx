import { useState, type FormEvent } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError, patch, post } from '../../api/client'
import { invalidateKeys, qk } from '../../api/queryKeys'
import {
  DAY_AVAILABILITY_LABELS,
  GYM_ACCESS_LABELS,
  RUNNING_ACCESS_LABELS,
  type DayAvailability,
  type DayAvailabilityEntry,
  type GymAccess,
  type RunningAccess,
  type Trip,
} from '../../api/types/travel'
import { Button, Input, NativeSelect } from '../../components/ui'
import { addDays, dateLabel } from '../../lib/format'
import { Select } from './shared'

const CONFLICT_MESSAGE = 'This trip changed since it loaded. The list was refreshed; try again.'

export function tripWriteError(error: Error): string {
  return error instanceof ApiError && error.code === 'version_conflict'
    ? CONFLICT_MESSAGE
    : error.message
}

export function TripForm({
  trip,
  homeTimezone,
  onSaved,
  onCancel,
}: {
  trip: Trip | null
  homeTimezone: string
  onSaved: () => void
  onCancel: () => void
}) {
  const qc = useQueryClient()
  const [version] = useState(trip?.version)
  const [start, setStart] = useState(trip?.start_date ?? '')
  const [end, setEnd] = useState(trip?.end_date ?? '')
  const [label, setLabel] = useState(trip?.destination_label ?? '')
  const [zone, setZone] = useState(trip?.destination_tz ?? homeTimezone)
  const [running, setRunning] = useState<RunningAccess | ''>(trip?.running_access ?? '')
  const [gym, setGym] = useState<GymAccess | ''>(trip?.gym_access ?? '')
  const [days, setDays] = useState<Record<string, DayAvailability | ''>>(() =>
    Object.fromEntries(
      (trip?.day_availability ?? []).map((entry) => [entry.date, entry.availability]),
    ),
  )
  const [clientError, setClientError] = useState<string | null>(null)
  const endRequired = trip === null || trip.source === 'manual'
  const zones = Intl.supportedValuesOf('timeZone')
  if (!zones.includes(zone)) zones.unshift(zone)
  const last = end || start
  const shown: string[] = []
  for (let day = start; day && day <= last && shown.length < 21; day = addDays(day, 1)) {
    shown.push(day)
  }
  const moreDays = shown.length === 21 && (shown.at(-1) ?? '') < last
  const save = useMutation({
    mutationFn: () => {
      const availability: DayAvailabilityEntry[] = []
      const availabilityEnd = end || addDays(start, 30)
      for (const date of Object.keys(days).sort()) {
        const entry = days[date]
        if (entry && start <= date && date <= availabilityEnd)
          availability.push({ date, availability: entry })
      }
      const fields = {
        start_date: start,
        end_date: end || null,
        destination_label: label.trim() || null,
        destination_tz: zone,
        running_access: running || null,
        gym_access: gym || null,
        day_availability: availability,
      }
      return trip
        ? patch<Trip>(`/trips/${encodeURIComponent(trip.id)}`, {
            expected_version: version,
            ...fields,
            status: 'confirmed',
          })
        : post<Trip>('/trips', { ...fields, end_date: end })
    },
    onSuccess: onSaved,
    onSettled: () => invalidateKeys(qc, [qk.tripsAll, qk.proposals]),
  })
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (trip?.version !== version) return
    if (end && end < start) {
      setClientError('End date must be on or after the start date.')
      return
    }
    setClientError(null)
    save.mutate()
  }
  const outdated = trip?.version !== version
  const error = outdated
    ? CONFLICT_MESSAGE
    : (clientError ?? (save.error && tripWriteError(save.error)))

  return (
    <form data-testid="trip-form" onSubmit={submit} className="space-y-3">
      <fieldset disabled={save.isPending} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="trip-start">Start date</label>
            <Input
              id="trip-start"
              type="date"
              required
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="trip-end">
              {endRequired ? 'End date' : 'End date (leave empty if unknown)'}
            </label>
            <Input
              id="trip-end"
              type="date"
              required={endRequired}
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="trip-destination">Destination</label>
            <Input
              id="trip-destination"
              maxLength={120}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>
          <div>
            <label htmlFor="trip-zone">Destination timezone</label>
            <NativeSelect id="trip-zone" value={zone} onChange={(e) => setZone(e.target.value)}>
              {zones.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </NativeSelect>
          </div>
          <div>
            <Select
              id="trip-running"
              label="Running access"
              value={running}
              options={{ '': 'Unknown', ...RUNNING_ACCESS_LABELS }}
              onChange={(value) => setRunning(value as RunningAccess | '')}
            />
          </div>
          <div>
            <Select
              id="trip-gym"
              label="Gym access"
              value={gym}
              options={{ '': 'Unknown', ...GYM_ACCESS_LABELS }}
              onChange={(value) => setGym(value as GymAccess | '')}
            />
          </div>
        </div>
        {shown.length > 0 && (
          <div className="space-y-2">
            <h4>Availability by day</h4>
            {moreDays && (
              <p className="notice muted">
                Showing the first 21 days. Saved choices for later days are kept.
              </p>
            )}
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shown.map((day) => (
                <div key={day}>
                  <label htmlFor={`trip-day-${day}`}>
                    {dateLabel(day, { weekday: 'short', month: 'short', day: 'numeric' })}
                  </label>
                  <NativeSelect
                    id={`trip-day-${day}`}
                    data-testid="day-availability-select"
                    data-date={day}
                    value={days[day] ?? ''}
                    onChange={(e) =>
                      setDays({ ...days, [day]: e.target.value as DayAvailability | '' })
                    }
                  >
                    <option value="">Unknown</option>
                    {Object.entries(DAY_AVAILABILITY_LABELS).map(([value, text]) => (
                      <option key={value} value={value}>
                        {text}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              ))}
            </div>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={outdated}>
            {trip ? 'Save and confirm' : 'Add trip'}
          </Button>
          <Button variant="link" type="button" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </fieldset>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
