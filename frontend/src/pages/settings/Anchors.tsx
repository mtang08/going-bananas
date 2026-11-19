import { Button, Input } from '../../components/ui'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  api,
  post,
  qk,
  invalidateKeys,
  validDate,
  dateLabel,
  fmtClock,
  fmtPaceFromSpeed,
  clockToSeconds,
  paceToSpeed,
  ANCHOR_KIND_LABELS,
  ANCHOR_UNIT,
  PROTOCOL_LABELS,
  type AnchorList,
  type AnchorKind,
  type AnchorProtocol,
  type AnchorConfidence,
  type Unit,
} from '../../api'
import { QueryState } from '../../components/QueryState'
import { ErrorText, Select } from './shared'

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
export function Anchors({
  unit,
  today,
  timezone,
}: {
  unit: Unit
  today: string
  timezone: string
}) {
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
    <>
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
    </>
  )
}
