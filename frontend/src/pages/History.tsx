import { Badge, Button, Card, Input, NativeSelect, Textarea } from '../components/ui'
import { Modal } from '../components/Modal'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, Plus } from 'lucide-react'
import {
  addDays,
  dateLabel,
  duration,
  localDate,
  patch,
  query,
  validDate,
  windowDays,
  type Activity,
  type Checkin,
  type Coverage,
  type ManualSession,
} from '../api'
import { ActivityDetail } from '../components/ActivityDetail'
import { ActivityTable } from '../components/ActivityTable'
import { CoverageStrip } from '../components/CoverageStrip'
import { Empty } from '../components/Empty'
import { QueryState } from '../components/QueryState'
import { useServer, type Unit } from '../components/shared'
export function History({ unit, onCheckin }: { unit: Unit; onCheckin: () => void }) {
  const [window, setWindow] = useState(() => ({
    start: addDays(localDate(), -27),
    end: localDate(),
  }))
  const [draftStart, setDraftStart] = useState(window.start),
    [draftEnd, setDraftEnd] = useState(window.end)
  const [sport, setSport] = useState(''),
    [cursor, setCursor] = useState<string | null>(null),
    [selected, setSelected] = useState<string | null>(null),
    [editing, setEditing] = useState<Checkin | null>(null),
    [editingManual, setEditingManual] = useState<ManualSession | null>(null)
  const { start, end } = window
  const span = windowDays(start, end)
  const dateError =
    !validDate(draftStart) || !validDate(draftEnd)
      ? 'Enter valid start and end dates.'
      : draftStart > draftEnd
        ? 'Start date must be on or before end date.'
        : draftEnd > localDate()
          ? 'End date cannot be in the future.'
          : windowDays(draftStart, draftEnd) > 366
            ? 'Choose a window of 366 dates or fewer.'
            : ''
  function selectWindow(nextStart: string, nextEnd: string) {
    setWindow({ start: nextStart, end: nextEnd })
    setDraftStart(nextStart)
    setDraftEnd(nextEnd)
    setCursor(null)
    setSelected(null)
  }
  function preset(days: number) {
    const last = localDate()
    selectWindow(addDays(last, 1 - days), last)
  }
  function shift(direction: -1 | 1) {
    const shiftedEnd = addDays(end, span * direction)
    const nextEnd = direction === 1 && shiftedEnd > localDate() ? localDate() : shiftedEnd
    selectWindow(addDays(nextEnd, 1 - span), nextEnd)
  }
  const activities = useServer<{
    items: Activity[]
    next_cursor: string | null
    timezone: string
    coverage: Coverage[]
  }>(
    ['activities', start, end, sport, cursor],
    `/activities${query({ start_date: start, end_date: end, sport, cursor, limit: 50 })}`,
  )
  const checkins = useServer<{
    items: Checkin[]
  }>(['checkins', start, end], `/checkins${query({ start_date: start, end_date: end })}`)
  const manuals = useServer<{
    items: ManualSession[]
  }>(['manuals', start, end], `/manual-sessions${query({ start_date: start, end_date: end })}`)
  const a = activities.data?.data
  return (
    <section className="page-content">
      <div className="page-heading">
        <div>
          <div className="eyebrow">THE RECORD</div>
          <h1>Training history.</h1>
          <p>Every session and observation keeps its own context.</p>
        </div>
        <Button onClick={onCheckin}>
          <Plus size={18} /> Record check-in
        </Button>
      </div>
      <div className="toolbar">
        <div className="segmented max-w-full flex-wrap" aria-label="History presets">
          <Button variant="ghost" onClick={() => preset(28)}>
            Latest 4 weeks
          </Button>
          <Button variant="ghost" onClick={() => preset(84)}>
            Latest 12 weeks
          </Button>
          <Button variant="ghost" onClick={() => preset(365)}>
            Latest year
          </Button>
        </div>
        <label className="select-label">
          Sport{' '}
          <NativeSelect
            value={sport}
            onChange={(e) => {
              setSport(e.target.value)
              setCursor(null)
            }}
          >
            <option value="">All sports</option>
            <option value="running">Running</option>
            <option value="strength">Strength</option>
            <option value="cycling">Cycling</option>
            <option value="walking">Walking</option>
          </NativeSelect>
        </label>
      </div>
      <form
        className="history-date-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (!dateError) selectWindow(draftStart, draftEnd)
        }}
      >
        <label className="select-label" htmlFor="history-start">
          Start date{' '}
          <Input
            id="history-start"
            type="date"
            value={draftStart}
            max={localDate()}
            onChange={(e) => setDraftStart(e.target.value)}
            required
          />
        </label>
        <label className="select-label" htmlFor="history-end">
          End date{' '}
          <Input
            id="history-end"
            type="date"
            value={draftEnd}
            max={localDate()}
            onChange={(e) => setDraftEnd(e.target.value)}
            required
          />
        </label>
        <Button type="submit" disabled={!!dateError}>
          Show dates
        </Button>
        <Button
          type="button"
          onClick={() => shift(-1)}
          aria-label="Previous date window"
          variant="outline"
        >
          <ChevronLeft size={16} /> Previous
        </Button>
        <Button
          type="button"
          onClick={() => shift(1)}
          disabled={end >= localDate()}
          aria-label="Next date window"
          variant="outline"
        >
          Next <ChevronRight size={16} />
        </Button>
        <span className="toolbar-note">
          {dateLabel(start, { month: 'short', day: 'numeric', year: 'numeric' })} –{' '}
          {dateLabel(end, { month: 'short', day: 'numeric', year: 'numeric' })}
        </span>
        {dateError && (
          <small className="error-text" role="alert">
            {dateError}
          </small>
        )}
      </form>
      <div className="grid history-grid">
        <Card>
          <div className="panel-head">
            <div>
              <h2>Activities</h2>
              <p>Imported and resolved records</p>
            </div>
            <Badge className="unit-pill">{unit}</Badge>
          </div>
          <QueryState
            loading={activities.isPending}
            error={activities.error}
            stale={!!activities.data}
            retry={() => activities.refetch()}
          >
            {a && (
              <>
                {a.items.length ? (
                  <ActivityTable items={a.items} unit={unit} onSelect={(x) => setSelected(x.id)} />
                ) : (
                  <Empty
                    title="No activities in this view"
                    text="Try a wider date range or check import coverage."
                  />
                )}
                <div className="pagination">
                  <Button disabled={!cursor} onClick={() => setCursor(null)} variant="outline">
                    First page
                  </Button>
                  <Button
                    disabled={!a.next_cursor}
                    onClick={() => setCursor(a.next_cursor)}
                    variant="outline"
                  >
                    Next page <ChevronRight size={15} />
                  </Button>
                </div>
                <CoverageStrip items={a.coverage} />
              </>
            )}
          </QueryState>
        </Card>
        <div className="side-stack">
          <Card>
            <div className="panel-head">
              <div>
                <h2>Check-ins</h2>
                <p>Symptoms and energy, as reported</p>
              </div>
            </div>
            <QueryState loading={checkins.isPending} error={checkins.error} stale={!!checkins.data}>
              {checkins.data &&
                (checkins.data.data.items.length ? (
                  <div className="timeline">
                    {checkins.data.data.items.map((c) => (
                      <div className="timeline-entry" key={c.id}>
                        <div className="timeline-date">{dateLabel(c.observed_at.slice(0, 10))}</div>
                        <div>
                          <strong>
                            {c.symptoms === 'none' ? 'No issues' : `${c.symptoms} symptoms`}
                          </strong>
                          <small>
                            {c.gait} gait · {c.feeling} energy
                          </small>
                          {c.associations?.map((a) => (
                            <small key={a.activity_id}>
                              {a.kind.replaceAll('_', ' ')} ·{' '}
                              {a.timing_uncertain
                                ? 'timing uncertain'
                                : `${a.elapsed_hours?.toFixed(1)}h later`}{' '}
                              · {a.day_label}
                            </small>
                          ))}
                          <Button onClick={() => setEditing(c)} variant="link">
                            Edit entry
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty title="No check-ins" text="Unreported days stay unreported." />
                ))}
            </QueryState>
          </Card>
          <Card>
            <div className="panel-head">
              <div>
                <h2>Manual sessions</h2>
                <p>Strength, mobility and other work</p>
              </div>
            </div>
            <QueryState loading={manuals.isPending} error={manuals.error} stale={!!manuals.data}>
              {manuals.data &&
                (manuals.data.data.items.length ? (
                  <div className="timeline">
                    {manuals.data.data.items.map((m) => (
                      <div className="timeline-entry" key={m.id}>
                        <div className="timeline-date">{dateLabel(m.date)}</div>
                        <div>
                          <strong>{m.kind.replaceAll('_', ' ')}</strong>
                          <small>
                            {duration(m.duration_s)}
                            {m.linked_activity_id ? ' · linked import' : ' · manual'}
                          </small>
                          <Button onClick={() => setEditingManual(m)} variant="link">
                            Edit session
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="No manual sessions"
                    text="Add one from the cycle day editor when needed."
                  />
                ))}
            </QueryState>
          </Card>
        </div>
      </div>
      {selected && <ActivityDetail id={selected} unit={unit} close={() => setSelected(null)} />}
      {editing && <EditCheckinModal checkin={editing} close={() => setEditing(null)} />}
      {editingManual && (
        <EditManualModal session={editingManual} close={() => setEditingManual(null)} />
      )}
    </section>
  )
}
function EditCheckinModal({ checkin, close }: { checkin: Checkin; close: () => void }) {
  const at = new Date(checkin.observed_at)
  const initial = `${localDate(at)}T${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
  const qc = useQueryClient(),
    [symptoms, setSymptoms] = useState(checkin.symptoms),
    [gait, setGait] = useState(checkin.gait),
    [feeling, setFeeling] = useState(checkin.feeling),
    [note, setNote] = useState(checkin.note || ''),
    [observed, setObserved] = useState(initial)
  const save = useMutation({
    mutationFn: () =>
      patch<Checkin>(`/checkins/${checkin.id}`, {
        expected_version: checkin.version,
        observed_at: new Date(observed).toISOString(),
        symptoms,
        gait,
        feeling,
        note,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['checkins'] })
      qc.invalidateQueries({ queryKey: ['coach'] })
      close()
    },
  })
  return (
    <Modal label="Edit check-in" close={close}>
      <div className="eyebrow">CORRECT AN ENTRY</div>
      <h2>Edit check-in</h2>
      <p>Earlier versions remain in the record. A concurrent edit asks you to reload.</p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div className="field">
          <label htmlFor="edit-observed">Observed at</label>
          <Input
            id="edit-observed"
            type="datetime-local"
            value={observed}
            onChange={(e) => setObserved(e.target.value)}
            required
          />
        </div>
        <div className="field">
          <label htmlFor="edit-symptoms">Symptoms</label>
          <NativeSelect
            id="edit-symptoms"
            value={symptoms}
            onChange={(e) => setSymptoms(e.target.value as Checkin['symptoms'])}
          >
            <option value="none">None</option>
            <option value="mild">Mild</option>
            <option value="moderate">Moderate</option>
            <option value="severe">Severe</option>
          </NativeSelect>
        </div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="edit-gait">Gait</label>
            <NativeSelect id="edit-gait" value={gait} onChange={(e) => setGait(e.target.value)}>
              <option value="normal">Normal</option>
              <option value="affected">Affected</option>
              <option value="unsure">Unsure</option>
            </NativeSelect>
          </div>
          <div className="field">
            <label htmlFor="edit-feeling">Energy</label>
            <NativeSelect
              id="edit-feeling"
              value={feeling}
              onChange={(e) => setFeeling(e.target.value)}
            >
              <option value="fresh">Fresh</option>
              <option value="usual">Usual</option>
              <option value="tired">Tired</option>
            </NativeSelect>
          </div>
        </div>
        <div className="field">
          <label htmlFor="edit-note">Note</label>
          <Textarea
            id="edit-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
          />
        </div>
        {save.error && (
          <p className="error-text" role="alert">
            {save.error.message}{' '}
            {save.error.message.includes('version') ? 'Reload the page and try again.' : ''}
          </p>
        )}
        <Button type="submit" disabled={save.isPending}>
          Save correction
        </Button>
      </form>
    </Modal>
  )
}
function EditManualModal({ session, close }: { session: ManualSession; close: () => void }) {
  const qc = useQueryClient(),
    [date, setDate] = useState(session.date),
    [kind, setKind] = useState(session.kind),
    [minutes, setMinutes] = useState(
      session.duration_s == null ? '' : String(Math.round(session.duration_s / 60)),
    ),
    [note, setNote] = useState(session.note || '')
  const save = useMutation({
    mutationFn: () =>
      patch<ManualSession>(`/manual-sessions/${session.id}`, {
        expected_version: session.version,
        date,
        kind,
        duration_s: minutes ? Number(minutes) * 60 : null,
        note,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['manuals'] })
      void qc.invalidateQueries({ queryKey: ['cycle-manuals'] })
      void qc.invalidateQueries({ queryKey: ['summary'] })
      close()
    },
  })
  return (
    <Modal label="Edit manual session" close={close}>
      <div className="eyebrow">CORRECT A SESSION</div>
      <h2>Edit manual session</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div className="form-grid">
          <div className="field">
            <label htmlFor="edit-manual-date">Date</label>
            <Input
              id="edit-manual-date"
              type="date"
              value={date}
              onChange={(e) => setDate(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="edit-manual-kind">Kind</label>
            <NativeSelect
              id="edit-manual-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              <option value="strength">Strength</option>
              <option value="mobility">Mobility</option>
              <option value="cycling">Cycling</option>
              <option value="other">Other</option>
            </NativeSelect>
          </div>
        </div>
        <div className="field">
          <label htmlFor="edit-manual-minutes">Duration in minutes · optional</label>
          <Input
            id="edit-manual-minutes"
            type="number"
            min="1"
            max="1440"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="edit-manual-note">Note</label>
          <Textarea
            id="edit-manual-note"
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        {save.error && (
          <p className="error-text" role="alert">
            {save.error.message}
          </p>
        )}
        <Button type="submit" disabled={save.isPending}>
          Save session correction
        </Button>
      </form>
    </Modal>
  )
}
