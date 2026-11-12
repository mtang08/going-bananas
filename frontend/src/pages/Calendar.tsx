import { Badge, Button, Card, Disclosure, Input, NativeSelect, Textarea } from '../components/ui'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  REASON_LABELS,
  RECIPE_LABELS,
  addDays,
  api,
  dateLabel,
  fmtDistance,
  fmtDuration,
  invalidateKeys,
  pageHref,
  post,
  put,
  qk,
  query,
} from '../api'
import type {
  Activity,
  CalendarDiff,
  CalendarEditsRequest,
  CalendarRollbackRequest,
  CalendarVersion,
  CalendarView,
  CalendarWriteResult,
  Completion,
  CompletionPut,
  SessionFields,
  SessionKind,
  SessionState,
  Unit,
} from '../api'
import { mondayOfWeek, SessionSummary } from '../components/PlanOverview'
import { Modal } from '../components/Modal'
import { Empty } from '../components/Empty'
import { QueryState } from '../components/QueryState'

type EditorState = { mode: 'add'; date: string } | { mode: 'edit' | 'move'; session: SessionState }

const KIND: Record<CalendarVersion['kind'], string> = {
  bootstrap: 'Setup',
  manual_edit: 'Manual edit',
  proposal_accept: 'Coach proposal accepted',
  rollback: 'Rollback',
  legacy_import: 'Legacy import',
}
const OP: Record<CalendarDiff['changes'][number]['op'], string> = {
  add: 'Added',
  modify: 'Modified',
  move: 'Moved',
  delete: 'Deleted',
}
const meters = (value: string, unit: Unit): number | null =>
  value.trim() ? Math.round(Number(value) * (unit === 'mi' ? 1609.344 : 1000)) : null
const seconds = (value: string): number | null =>
  value.trim() ? Math.round(Number(value) * 60) : null

export function Calendar({ unit }: { unit: Unit }) {
  const qc = useQueryClient()
  const [viewVersion, setViewVersion] = useState<number | null>(null)
  const [editor, setEditor] = useState<EditorState | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [confirmRestore, setConfirmRestore] = useState<number | null>(null)
  const [restoreReason, setRestoreReason] = useState('')
  const [outcomeFor, setOutcomeFor] = useState<SessionState | null>(null)
  const [selectedRun, setSelectedRun] = useState('')
  const [message, setMessage] = useState<string | null>(null)
  const [preservedIds, setPreservedIds] = useState<string[]>([])
  const [writeError, setWriteError] = useState<Error | null>(null)
  const view = useQuery({
    queryKey: qk.calendarView(viewVersion ?? 'head'),
    queryFn: () => api<CalendarView>(`/calendar${query({ version: viewVersion ?? undefined })}`),
  })
  const versions = useQuery({
    queryKey: qk.calendarVersions,
    queryFn: () => api<{ items: CalendarVersion[] }>('/calendar/versions?limit=20'),
  })
  const diff = useQuery({
    queryKey: qk.calendarDiff((viewVersion ?? 1) - 1, viewVersion ?? 1),
    enabled: viewVersion !== null && viewVersion > 1,
    queryFn: () =>
      api<CalendarDiff>(`/calendar/diff${query({ from: viewVersion! - 1, to: viewVersion! })}`),
  })
  const data = view.data?.data
  const today = data?.today ?? ''
  const nearDate = outcomeFor?.local_date ?? today
  const near = useQuery({
    queryKey: qk.activitiesNear(
      addDays(nearDate || '2026-01-01', -1),
      addDays(nearDate || '2026-01-01', 1),
    ),
    enabled: outcomeFor !== null,
    queryFn: () =>
      api<{ items: Activity[] }>(
        `/activities${query({
          start_date: addDays(nearDate, -1),
          end_date: addDays(nearDate, 1),
          sport: 'running',
          limit: 50,
        })}`,
      ),
  })
  const edits = useMutation({
    mutationFn: (body: CalendarEditsRequest) => post<CalendarWriteResult>('/calendar/edits', body),
    onSuccess: (response) => {
      invalidateKeys(qc, [qk.calendar, qk.metrics, qk.prompts, qk.coach])
      setEditor(null)
      setConfirmDelete(null)
      setWriteError(null)
      setPreservedIds([])
      const result = response.data
      setMessage(
        result.stale_proposals.length
          ? `This edit made ${result.stale_proposals.length} pending coach proposal(s) stale.`
          : `Saved as version ${result.version}.`,
      )
    },
    onError: (error) => setWriteError(error),
  })
  const rollback = useMutation({
    mutationFn: (body: CalendarRollbackRequest) =>
      post<CalendarWriteResult>('/calendar/rollback', body),
    onSuccess: (response, body) => {
      invalidateKeys(qc, [qk.calendar, qk.metrics, qk.prompts, qk.coach])
      setConfirmRestore(null)
      setViewVersion(null)
      setWriteError(null)
      setPreservedIds(response.data.preserved_session_uids)
      setMessage(`Restored version ${body.to_version} as version ${response.data.version}.`)
    },
    onError: (error) => setWriteError(error),
  })
  const outcome = useMutation({
    mutationFn: ({ uid, body }: { uid: string; body: CompletionPut }) =>
      put<Completion>(`/calendar/completions/${encodeURIComponent(uid)}`, body),
    onSuccess: () => {
      invalidateKeys(qc, [qk.calendar, qk.metrics, qk.prompts])
      setOutcomeFor(null)
      setSelectedRun('')
      setWriteError(null)
      setMessage('Outcome saved.')
    },
    onError: (error) => setWriteError(error),
  })
  const saveOutcome = (body: CompletionPut) => {
    if (!outcomeFor) return
    const current = data?.completions.find((c) => c.session_uid === outcomeFor.session_uid)
    outcome.mutate({
      uid: outcomeFor.session_uid,
      body: current ? { ...body, expected_version: current.version } : body,
    })
  }
  const showError = writeError && (
    <p className="error-text" role="alert">
      {writeError instanceof ApiError && writeError.code === 'calendar_head_moved' ? (
        <>
          The calendar changed since you loaded it. Reload and try again.{' '}
          <Button
            variant="outline"
            onClick={() => {
              setEditor(null)
              setOutcomeFor(null)
              setSelectedRun('')
              setConfirmDelete(null)
              setConfirmRestore(null)
              invalidateKeys(qc, [qk.calendar])
              setWriteError(null)
            }}
          >
            Reload calendar
          </Button>
        </>
      ) : (
        writeError.message
      )}
    </p>
  )
  const renderDay = (day: string) => {
    if (!data) return null
    const sessions = data.sessions
      .filter((s) => !s.deleted && s.local_date === day)
      .sort((a, b) => a.slot - b.slot)
    const extra = data.completions.filter((c) => c.status === 'extra' && c.local_date === day)
    const recorded = (data.recorded_runs ?? []).filter((run) => run.local_date === day)
    const writable = viewVersion === null
    return (
      <div
        className={`calendar-day${day === today ? ' is-today' : ''}`}
        data-testid="calendar-day"
        data-date={day}
        key={day}
      >
        <h3>{dateLabel(day, { weekday: 'long', month: 'short', day: 'numeric' })}</h3>
        {sessions.map((s) => {
          const completion = data.completions.find((c) => c.session_uid === s.session_uid)
          const protectedCompletion =
            completion &&
            (completion.status === 'skipped' ||
              Boolean(
                completion.activity_id ||
                completion.strong_workout_id ||
                completion.manual_session_id,
              ))
          const canEdit = writable && day >= today && !s.locked && !protectedCompletion
          const canRecord =
            writable && day < today && (!completion || completion.status === 'unknown')
          return (
            <div
              className={`session-row certainty-${s.certainty}`}
              data-testid="session-row"
              data-date={s.local_date}
              key={s.session_uid}
            >
              <SessionSummary session={s} completion={completion} today={today} unit={unit}>
                {completion?.modification_reason && (
                  <small>Reason: {REASON_LABELS[completion.modification_reason]}</small>
                )}
                {completion?.activity_id && (
                  <a href={pageHref.activity(completion.activity_id)}>Open run</a>
                )}
                {canEdit && (
                  <div className="coach-actions">
                    <Button
                      variant="link"
                      onClick={() => {
                        setEditor({ mode: 'edit', session: s })
                        setMessage(null)
                      }}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="link"
                      onClick={() => {
                        setEditor({ mode: 'move', session: s })
                        setMessage(null)
                      }}
                    >
                      Move
                    </Button>
                    {confirmDelete === s.session_uid ? (
                      <>
                        Delete this session?{' '}
                        <Button
                          variant="outline"
                          disabled={edits.isPending}
                          onClick={() =>
                            edits.mutate({
                              expected_head: data.head,
                              edits: [{ op: 'delete', session_uid: s.session_uid, fields: {} }],
                            })
                          }
                        >
                          Confirm delete
                        </Button>
                        <Button variant="link" onClick={() => setConfirmDelete(null)}>
                          Cancel
                        </Button>
                      </>
                    ) : (
                      <Button variant="link" onClick={() => setConfirmDelete(s.session_uid)}>
                        Delete
                      </Button>
                    )}
                  </div>
                )}
                {canRecord && (
                  <Button
                    variant="link"
                    onClick={() => {
                      setOutcomeFor(s)
                      setMessage(null)
                    }}
                  >
                    Record outcome
                  </Button>
                )}
              </SessionSummary>
            </div>
          )
        })}
        {sessions.length === 0 && extra.length === 0 && recorded.length === 0 && (
          <p className="day-empty">No session</p>
        )}
        {recorded.map((run) => (
          <div className="session-row" data-testid="session-row" data-date={day} key={run.activity_id}>
            <strong>Recorded run</strong>
            <p>{fmtDistance(run.distance_m, unit)} · {fmtDuration(run.timer_s)}</p>
            <a href={pageHref.activity(run.activity_id)}>Open run</a>
          </div>
        ))}
        {extra.map((c) => (
          <div className="session-row extra" data-testid="session-row" data-date={day} key={c.id}>
            Extra run (not in the plan){' '}
            {c.activity_id && <a href={pageHref.activity(c.activity_id)}>Open run</a>}
          </div>
        ))}
        {writable && day >= today && (
          <Button
            variant="link"
            onClick={() => {
              setEditor({ mode: 'add', date: day })
              setMessage(null)
            }}
          >
            Add session
          </Button>
        )}
      </div>
    )
  }
  return (
    <section className="page-content calendar-page space-y-5">
      <div className="page-heading">
        <div>
          <div className="eyebrow">YOUR TRAINING WEEKS</div>
          <h1>Calendar.</h1>
          <p>Edit, move, add, or delete sessions. Every change is saved as a new version.</p>
        </div>
        {data && data.head !== 0 && <Badge className="unit-pill">Version {data.head}</Badge>}
      </div>
      {message && (
        <p className="success-text" role="status">
          {message}
        </p>
      )}
      {preservedIds.length > 0 && (
        <p className="notice muted">
          Completed, locked and historical sessions were preserved. Preserved:{' '}
          {preservedIds.join(', ')}
        </p>
      )}
      {!editor && !outcomeFor && showError}
      <QueryState loading={view.isPending} error={view.error} retry={() => void view.refetch()}>
        {data &&
          (data.head === 0 ? (
            <>
              <Empty
                title="No calendar yet"
                text="Finish setup in Settings to fill the next 14 days."
              />
              <a href={pageHref.settings}>Open setup</a>
            </>
          ) : (
            <>
              {viewVersion !== null && (
                <div className="notice muted">
                  Viewing version {viewVersion} (read-only).{' '}
                  <Button variant="link" onClick={() => setViewVersion(null)}>
                    Back to current
                  </Button>
                </div>
              )}
              {viewVersion !== null && diff.data && (
                <Card>
                  <h3>Changes in version {viewVersion}</h3>
                  <ul>
                    {diff.data.data.changes.map((change, i) => (
                      <li key={`${change.session_uid}:${i}`}>
                        {OP[change.op]} {(change.after ?? change.before)?.intent ?? 'session'}
                        {change.op === 'move' &&
                          change.before?.local_date &&
                          change.after?.local_date &&
                          ` (${dateLabel(change.before.local_date)} → ${dateLabel(change.after.local_date)})`}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
              {[0, 1].map((week) => (
                <Card key={week}>
                  <div className="panel-head">
                    <h2>{week === 0 ? 'This week' : 'Next week'}</h2>
                    <span>Monday–Sunday</span>
                  </div>
                  <div className="calendar-week-grid">
                    {Array.from({ length: 7 }, (_, i) =>
                      renderDay(addDays(mondayOfWeek(today), week * 7 + i)),
                    )}
                  </div>
                </Card>
              ))}
              <Disclosure variant="card" className="calendar-history">
                <summary>Calendar history</summary>
                <h2>Past 7 days</h2>
                {Array.from({ length: 7 }, (_, i) => renderDay(addDays(today, i - 7)))}
                <h2>Version history</h2>
                {versions.error && (
                  <p role="alert" className="error-text">
                    {versions.error.message}
                  </p>
                )}
                {versions.data?.data.items.map((version) => {
                  const eligible =
                    viewVersion === null &&
                    data.undo?.eligible &&
                    data.undo.target_version === version.number
                  return (
                    <div className="version-row" data-testid="version-row" key={version.id}>
                      <strong>
                        v{version.number} · {KIND[version.kind]}
                      </strong>
                      {version.restored_from_number !== null && (
                        <> (restored v{version.restored_from_number})</>
                      )}
                      {' · '}
                      {version.actor === 'user'
                        ? 'You'
                        : version.actor === 'system'
                          ? 'System'
                          : 'Coach'}
                      {' · '}
                      {new Date(version.created_at).toLocaleString()}
                      {version.reason && <span> · {version.reason}</span>}
                      <Button
                        variant="link"
                        onClick={() =>
                          setViewVersion(version.number === data.head ? null : version.number)
                        }
                      >
                        View
                      </Button>
                      {eligible &&
                        (confirmRestore === version.number ? (
                          <div>
                            Restore version {version.number}? This creates a new version.
                            <p>Completed, locked and historical sessions were preserved.</p>
                            {data.undo?.protected_session_uids.length ? (
                              <p>Preserved: {data.undo.protected_session_uids.join(', ')}</p>
                            ) : null}
                            <label htmlFor="restore-reason">Reason (optional)</label>
                            <Input
                              id="restore-reason"
                              value={restoreReason}
                              onChange={(e) => setRestoreReason(e.target.value)}
                            />
                            <Button
                              variant="outline"
                              disabled={rollback.isPending}
                              onClick={() =>
                                rollback.mutate({
                                  expected_head: data.head,
                                  to_version: version.number,
                                  ...(restoreReason.trim() ? { reason: restoreReason.trim() } : {}),
                                })
                              }
                            >
                              Confirm restore
                            </Button>
                            <Button variant="link" onClick={() => setConfirmRestore(null)}>
                              Cancel
                            </Button>
                          </div>
                        ) : (
                          <Button
                            variant="link"
                            onClick={() => {
                              setConfirmRestore(version.number)
                              setRestoreReason('')
                            }}
                          >
                            Restore
                          </Button>
                        ))}
                    </div>
                  )
                })}
              </Disclosure>
            </>
          ))}
      </QueryState>
      {editor && data && (
        <SessionEditor
          key={editor.mode === 'add' ? editor.date : editor.session.session_uid + editor.mode}
          editor={editor}
          unit={unit}
          today={today}
          sessions={data.sessions}
          pending={edits.isPending}
          onCancel={() => setEditor(null)}
          error={showError}
          onSave={(body) => edits.mutate({ expected_head: data.head, ...body })}
        />
      )}
      {outcomeFor && (
        <Modal
          label="Record outcome"
          close={() => {
            setOutcomeFor(null)
            setSelectedRun('')
          }}
        >
          <h2>Record outcome</h2>
          <p>Missed sessions stay in the record. Nothing is rescheduled automatically.</p>
          {showError}
          <div className="coach-actions">
            <Button
              variant="outline"
              disabled={outcome.isPending}
              onClick={() => saveOutcome({ status: 'skipped' })}
            >
              Skipped
            </Button>
            <Button
              variant="ghost"
              disabled={outcome.isPending}
              onClick={() => saveOutcome({ status: 'unknown' })}
            >
              Not recorded
            </Button>
          </div>
          <label htmlFor="outcome-run">Link a run</label>
          <NativeSelect
            id="outcome-run"
            value={selectedRun}
            onChange={(e) => setSelectedRun(e.target.value)}
          >
            <option value="">Select a run</option>
            {near.data?.data.items.map((a) => (
              <option value={a.id} key={a.id}>
                {dateLabel(a.local_date)} · {fmtDistance(a.distance_m, unit)}
              </option>
            ))}
          </NativeSelect>
          {near.error && (
            <p className="error-text" role="alert">
              {near.error.message}
            </p>
          )}
          <Button
            variant="outline"
            disabled={!selectedRun || outcome.isPending}
            onClick={() => saveOutcome({ activity_id: selectedRun })}
          >
            Link run
          </Button>
          <Button
            variant="link"
            onClick={() => {
              setOutcomeFor(null)
              setSelectedRun('')
            }}
          >
            Cancel
          </Button>
        </Modal>
      )}
    </section>
  )
}

function SessionEditor({
  editor,
  unit,
  today,
  sessions,
  pending,
  onCancel,
  error,
  onSave,
}: {
  editor: EditorState
  unit: Unit
  today: string
  sessions: SessionState[]
  pending: boolean
  onCancel: () => void
  error: React.ReactNode
  onSave: (body: Omit<CalendarEditsRequest, 'expected_head'>) => void
}) {
  const session = editor.mode === 'add' ? null : editor.session
  const [kind, setKind] = useState<SessionKind>(session?.kind ?? 'run')
  const [recipe, setRecipe] = useState(
    session?.recipe_id ?? (editor.mode === 'add' ? 'REC001' : ''),
  )
  const [intent, setIntent] = useState(session?.intent ?? '')
  const [duration, setDuration] = useState(
    session?.planned_duration_s == null ? '' : String(session.planned_duration_s / 60),
  )
  const initialDistance =
    session?.planned_distance_m == null
      ? ''
      : String(Number((session.planned_distance_m / (unit === 'mi' ? 1609.344 : 1000)).toFixed(3)))
  const [distance, setDistance] = useState(initialDistance)
  const [notes, setNotes] = useState(session?.notes ?? '')
  const [reason, setReason] = useState('')
  const [moveDate, setMoveDate] = useState(session?.local_date ?? today)
  const [localError, setLocalError] = useState<string | null>(null)
  const submit = () => {
    if (editor.mode === 'move') {
      if (!session || moveDate === session.local_date) {
        setLocalError('Pick a different date.')
        return
      }
      if (moveDate < today || moveDate > addDays(today, 13)) {
        setLocalError('Pick a date in the next 14 days.')
        return
      }
      onSave({
        edits: [{ op: 'move', session_uid: session.session_uid, fields: { local_date: moveDate } }],
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      })
      return
    }
    if (!intent.trim()) {
      setLocalError('Intent is required.')
      return
    }
    if (duration && (!Number.isFinite(Number(duration)) || Number(duration) < 1)) {
      setLocalError('Enter a valid duration.')
      return
    }
    if (distance && (!Number.isFinite(Number(distance)) || Number(distance) <= 0)) {
      setLocalError('Enter a valid distance.')
      return
    }
    const current: Partial<SessionFields> = {
      kind,
      recipe_id: kind === 'run' ? recipe || null : null,
      intent: intent.trim(),
      planned_duration_s: seconds(duration),
      planned_distance_m: meters(distance, unit),
      notes: notes || null,
    }
    if (editor.mode === 'add') {
      const daySlots = sessions
        .filter((s) => !s.deleted && s.local_date === editor.date)
        .map((s) => s.slot)
      onSave({
        edits: [
          {
            op: 'add',
            fields: {
              local_date: editor.date,
              slot: daySlots.length ? Math.max(...daySlots) + 1 : 0,
              ...current,
              custom: false,
              structure: null,
              strength_slot_id: null,
            },
          },
        ],
        ...(reason.trim() ? { reason: reason.trim() } : {}),
      })
      return
    }
    if (!session) return
    if (session.placeholder && (kind !== 'run' || recipe !== '')) current.placeholder = false
    const changed = Object.fromEntries(
      Object.entries(current).filter(([key, value]) =>
        key === 'recipe_id' && recipe === '' && kind === 'run'
          ? false
          : key === 'planned_distance_m' && distance === initialDistance
            ? false
            : value !== session[key as keyof SessionState],
      ),
    ) as Partial<SessionFields>
    if (!Object.keys(changed).length) {
      setLocalError('No changes to save.')
      return
    }
    onSave({
      edits: [{ op: 'modify', session_uid: session.session_uid, fields: changed }],
      ...(reason.trim() ? { reason: reason.trim() } : {}),
    })
  }
  return (
    <Modal
      close={onCancel}
      label={
        editor.mode === 'add'
          ? 'Add session'
          : editor.mode === 'move'
            ? 'Move session'
            : 'Edit session'
      }
    >
      <h2>
        {editor.mode === 'move'
          ? 'Move session'
          : editor.mode === 'add'
            ? 'Add session'
            : 'Edit session'}
      </h2>
      {error}
      {localError && (
        <p className="error-text" role="alert">
          {localError}
        </p>
      )}
      {editor.mode === 'move' ? (
        <>
          <label htmlFor="move-date">New date</label>
          <Input
            id="move-date"
            type="date"
            required
            min={today}
            max={addDays(today, 13)}
            value={moveDate}
            onChange={(e) => setMoveDate(e.target.value)}
          />
        </>
      ) : (
        <>
          <label htmlFor="session-kind">Type</label>
          <NativeSelect
            id="session-kind"
            value={kind}
            onChange={(e) => setKind(e.target.value as SessionKind)}
          >
            <option value="run">Run</option>
            <option value="strength">Strength</option>
            <option value="cross">Cross-training</option>
            <option value="rest">Rest</option>
            <option value="mobility">Mobility</option>
          </NativeSelect>
          {kind === 'run' && (
            <>
              <label htmlFor="session-recipe">Session</label>
              <NativeSelect
                id="session-recipe"
                value={recipe}
                onChange={(e) => setRecipe(e.target.value)}
              >
                {session?.recipe_id === null && (
                  <option value="">
                    {session.custom ? 'Custom run' : 'Quality slot — selected at first review'}
                  </option>
                )}
                {Object.entries(RECIPE_LABELS).map(([id, label]) => (
                  <option key={id} value={id}>
                    {id} · {label}
                  </option>
                ))}
              </NativeSelect>
            </>
          )}
          <label htmlFor="session-intent">Intent</label>
          <Input
            id="session-intent"
            required
            maxLength={200}
            value={intent}
            onChange={(e) => setIntent(e.target.value)}
          />
          <label htmlFor="session-duration">Planned duration (minutes)</label>
          <Input
            id="session-duration"
            type="number"
            min="1"
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
          />
          <label htmlFor="session-distance">Planned distance ({unit})</label>
          <Input
            id="session-distance"
            type="number"
            step="0.1"
            value={distance}
            onChange={(e) => setDistance(e.target.value)}
          />
          <label htmlFor="session-notes">Notes</label>
          <Textarea id="session-notes" value={notes} onChange={(e) => setNotes(e.target.value)} />
        </>
      )}
      <label htmlFor="edit-reason">Reason for change (optional)</label>
      <Input id="edit-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="coach-actions">
        <Button variant="outline" disabled={pending} onClick={submit}>
          {editor.mode === 'move' ? 'Save move' : 'Save session'}
        </Button>
        <Button variant="link" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Modal>
  )
}
