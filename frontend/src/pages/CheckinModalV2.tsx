import { Badge, Button, Input, NativeSelect, Textarea } from '../components/ui'
import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Modal } from '../components/Modal'
import {
  api,
  post,
  put,
  qk,
  invalidateKeys,
  DECISION_LABELS,
  SIDE_LABELS,
  TIMING_LABELS,
  REASON_LABELS,
  statusText,
  type ActivityExecution,
  type CheckinCreate,
  type CheckinRequest,
  type CheckinV2,
  type Completion,
  type ContextTag,
  type DailyGuidance,
  type GaitChange,
  type Illness,
  type ModificationReason,
  type RpeResult,
  type Side,
  type SymptomTiming,
} from '../api'

const LABEL = {
  exception: 'Record check-in',
  post_run: 'Session RPE',
  delayed_followup: 'Delayed-response check',
}
type SymptomRow = { site: string; side: Side; severity: string; timing: SymptomTiming }
type Pain = 'yes' | 'no' | null
const newRow = (timing: SymptomTiming): SymptomRow => ({
  site: '',
  side: 'left',
  severity: '',
  timing,
})
function SymptomFields({
  pain,
  setPain,
  rows,
  onChange,
  defaultTiming,
}: {
  pain: Pain
  setPain: (pain: Pain) => void
  rows: SymptomRow[]
  onChange: (rows: SymptomRow[]) => void
  defaultTiming: SymptomTiming
}) {
  const update = (i: number, change: Partial<SymptomRow>) =>
    onChange(rows.map((r, n) => (n === i ? { ...r, ...change } : r)))
  return (
    <fieldset>
      <legend>Any pain?</legend>
      {(['no', 'yes'] as const).map((v) => (
        <Button
          variant={pain === v ? 'default' : 'outline'}
          key={v}
          type="button"
          className={`choice ${pain === v ? 'active' : ''}`}
          aria-pressed={pain === v}
          onClick={() => {
            setPain(v)
            if (v === 'yes' && rows.length === 0) onChange([newRow(defaultTiming)])
          }}
        >
          {v === 'yes' ? 'Yes' : 'No'}
        </Button>
      ))}
      {pain === 'yes' && (
        <>
          {rows.map((r, i) => (
            <div className="symptom-row" key={i}>
              <label htmlFor={`symptom-${i}-site`}>Where?</label>
              <Input
                id={`symptom-${i}-site`}
                value={r.site}
                maxLength={60}
                placeholder="e.g. posterior tibial tendon"
                onChange={(e) => update(i, { site: e.target.value })}
              />
              <label htmlFor={`symptom-${i}-side`}>Side</label>
              <NativeSelect
                id={`symptom-${i}-side`}
                value={r.side}
                onChange={(e) => update(i, { side: e.target.value as Side })}
              >
                {Object.entries(SIDE_LABELS).map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
              <label htmlFor={`symptom-${i}-severity`}>Severity (0–10)</label>
              <Input
                id={`symptom-${i}-severity`}
                type="number"
                min={0}
                max={10}
                step={0.5}
                value={r.severity}
                onChange={(e) => update(i, { severity: e.target.value })}
              />
              <label htmlFor={`symptom-${i}-timing`}>When did it start?</label>
              <NativeSelect
                id={`symptom-${i}-timing`}
                value={r.timing}
                onChange={(e) => update(i, { timing: e.target.value as SymptomTiming })}
              >
                {Object.entries(TIMING_LABELS).map(([v, label]) => (
                  <option key={v} value={v}>
                    {label}
                  </option>
                ))}
              </NativeSelect>
              {rows.length > 1 && (
                <Button
                  variant="link"
                  type="button"
                  onClick={() => onChange(rows.filter((_, n) => n !== i))}
                >
                  Remove
                </Button>
              )}
            </div>
          ))}
          <Button
            variant="link"
            type="button"
            onClick={() => onChange([...rows, newRow(defaultTiming)])}
          >
            Add another site
          </Button>
        </>
      )}
    </fieldset>
  )
}

type Submission = {
  signature: string
  body: CheckinCreate
  stage: number
  completion: Completion | null
  rpe: number | null
  reason: ModificationReason | ''
  reasonNote: string
}
export function CheckinModalV2({
  request,
  close,
}: {
  request?: CheckinRequest | null
  close: () => void
}) {
  const kind = request?.kind ?? 'exception',
    activityId = request?.activityId ?? null
  const qc = useQueryClient()
  const [initialKey] = useState(() => crypto.randomUUID())
  const [fatigue, setFatigue] = useState(''),
    [illness, setIllness] = useState<Illness | ''>(''),
    [gait, setGait] = useState<GaitChange | ''>('')
  const [pain, setPain] = useState<Pain>(null),
    [rows, setRows] = useState<SymptomRow[]>([])
  const [tags, setTags] = useState<ContextTag[]>([]),
    [note, setNote] = useState('')
  const [rpe, setRpe] = useState<number | null>(null),
    [reason, setReason] = useState<ModificationReason | ''>(''),
    [reasonNote, setReasonNote] = useState('')
  const [result, setResult] = useState<DailyGuidance | null>(null)
  const pending = useRef<Submission | null>(null)
  const execution = useQuery({
    queryKey: qk.activityExecution(activityId ?? ''),
    queryFn: () =>
      api<ActivityExecution>(`/activities/${encodeURIComponent(activityId!)}/execution`),
    enabled: kind === 'post_run' && !!activityId,
  })
  const completion = execution.data?.data.completion ?? null
  const changed =
    completion !== null &&
    completion.status !== 'completed_as_planned' &&
    completion.status !== 'extra'
  const mutation = useMutation({
    mutationFn: async () => {
      if (kind === 'post_run' && !activityId) throw new Error('No run selected.')
      if (kind === 'delayed_followup' && pain === null) throw new Error('Answer the pain question.')
      if (kind === 'delayed_followup' && !gait) throw new Error('Answer the gait question.')
      if (
        kind === 'exception' &&
        !fatigue &&
        !illness &&
        !gait &&
        pain === null &&
        tags.length === 0 &&
        !note.trim()
      )
        throw new Error('Report at least one item.')
      if (pain === 'yes')
        for (const row of rows) {
          if (!row.site.trim()) throw new Error('Enter where it hurts.')
          if (
            row.severity === '' ||
            !Number.isFinite(Number(row.severity)) ||
            Number(row.severity) < 0 ||
            Number(row.severity) > 10
          )
            throw new Error('Severity must be between 0 and 10.')
          if (Math.abs(Number(row.severity) * 10 - Math.round(Number(row.severity) * 10)) > 1e-8)
            throw new Error('Use at most one decimal place for severity.')
        }
      const fields = {
        kind,
        fatigue: fatigue === '' ? null : Number(fatigue),
        illness: illness || null,
        gait_change: gait || null,
        context_tags: tags,
        symptoms:
          pain === 'yes'
            ? rows.map((row) => ({ ...row, site: row.site.trim(), severity: Number(row.severity) }))
            : [],
        activity_id: activityId,
        prompt_id: request?.prompt?.id ?? null,
        note: note.trim() || null,
      }
      const signature = JSON.stringify({ fields, rpe, reason, reasonNote })
      if (!pending.current || pending.current.signature !== signature)
        pending.current = {
          signature,
          body: {
            ...fields,
            observed_at: new Date().toISOString(),
            idempotency_key: pending.current ? crypto.randomUUID() : initialKey,
          },
          stage: 0,
          completion: changed ? completion : null,
          rpe,
          reason,
          reasonNote: reasonNote.trim(),
        }
      const submission = pending.current
      if (kind === 'post_run') {
        if (submission.rpe === null) throw new Error('Choose an RPE.')
        if (submission.stage < 1) {
          await put<RpeResult>(`/activities/${encodeURIComponent(activityId!)}/rpe`, {
            rpe: submission.rpe,
          })
          submission.stage = 1
        }
        const c = submission.completion
        if (submission.stage < 2) {
          if (c && submission.reason) {
            const updated = await put<Completion>(
              `/calendar/completions/${encodeURIComponent(c.session_uid)}`,
              {
                expected_version: c.version,
                activity_id: activityId,
                modification_reason: submission.reason,
                reason_note: submission.reasonNote || null,
              },
            )
            qc.setQueryData(
              qk.activityExecution(activityId!),
              execution.data
                ? { ...execution.data, data: { ...execution.data.data, completion: updated.data } }
                : undefined,
            )
          }
          submission.stage = 2
        }
        if (request?.prompt || submission.body.note)
          return (await post<CheckinV2>('/v2/checkins', submission.body)).data
        return null
      }
      return (await post<CheckinV2>('/v2/checkins', submission.body)).data
    },
    onSuccess: (data) => {
      invalidateKeys(qc, [qk.checkins, qk.prompts, qk.metrics, qk.calendar])
      if (kind === 'exception') {
        const guidance = data?.daily_guidance ?? null
        qc.setQueryData(qk.coachDaily, guidance)
        invalidateKeys(qc, [qk.coachDaily])
        if (guidance) setResult(guidance)
        else close()
      } else {
        if (kind === 'post_run' && activityId)
          invalidateKeys(qc, [qk.activity(activityId), qk.activityExecution(activityId)])
        close()
      }
    },
  })
  const gaitField = (
    <>
      <label htmlFor="checkin-gait">Gait change?</label>
      <NativeSelect
        id="checkin-gait"
        value={gait}
        onChange={(e) => setGait(e.target.value as GaitChange | '')}
      >
        <option value="">{kind === 'delayed_followup' ? 'Choose' : 'Not reported'}</option>
        <option value="no">No</option>
        <option value="yes">Yes</option>
        <option value="unsure">Not sure</option>
      </NativeSelect>
    </>
  )
  return (
    <Modal label={LABEL[kind]} className="checkin-modal" close={close}>
      {result ? (
        <>
          <h3>Today's guidance</h3>
          <Badge className={`status-chip ${result.decision}`}>
            {DECISION_LABELS[result.decision]}
          </Badge>
          <p>{result.rationale}</p>
          {result.coach_review_suggested && (
            <div className="notice warning">
              Coach review suggested. Run the running-coach skill (daily review) before training.
            </div>
          )}
          {result.missing_inputs.length > 0 && (
            <small>Missing inputs: {result.missing_inputs.map(statusText).join(', ')}</small>
          )}
          <Button onClick={close}>Done</Button>
        </>
      ) : (
        <form
          noValidate
          onSubmit={(e) => {
            e.preventDefault()
            mutation.mutate()
          }}
        >
          <fieldset disabled={mutation.isPending}>
            {kind === 'exception' && (
              <>
                <span className="eyebrow">CHECK-IN</span>
                <h2>Something to report?</h2>
                <p>
                  Report pain, gait change, illness, fatigue, or context. Without a check-in, the
                  planned session stands.
                </p>
                <label htmlFor="checkin-fatigue">Fatigue (0–10)</label>
                <NativeSelect
                  id="checkin-fatigue"
                  value={fatigue}
                  onChange={(e) => setFatigue(e.target.value)}
                >
                  <option value="">Not reported</option>
                  {Array.from({ length: 11 }, (_, n) => (
                    <option value={n} key={n}>
                      {n}
                    </option>
                  ))}
                </NativeSelect>
              </>
            )}
            {kind !== 'post_run' && (
              <>
                {kind === 'delayed_followup' && (
                  <>
                    <span className="eyebrow">DELAYED-RESPONSE CHECK</span>
                    <h2>Any pain since this run?</h2>
                    <p>
                      Symptoms can show up 16–48 hours after a longer run. Report what you notice.
                    </p>
                  </>
                )}
                <SymptomFields
                  pain={pain}
                  setPain={setPain}
                  rows={rows}
                  onChange={setRows}
                  defaultTiming={kind === 'delayed_followup' ? 'hours_24_48' : 'unknown'}
                />
                {gaitField}
              </>
            )}
            {kind === 'exception' && (
              <>
                <label htmlFor="checkin-illness">Illness</label>
                <NativeSelect
                  id="checkin-illness"
                  value={illness}
                  onChange={(e) => setIllness(e.target.value as Illness | '')}
                >
                  <option value="">Not reported</option>
                  <option value="none">None</option>
                  <option value="possible">Possible</option>
                  <option value="present">Present</option>
                </NativeSelect>
                <fieldset>
                  <legend>Context</legend>
                  {Object.entries({
                    heat: 'Heat',
                    travel: 'Travel',
                    poor_sleep: 'Poor sleep',
                    unusual_surface: 'Unusual surface',
                    equipment: 'Equipment',
                  }).map(([value, label]) => (
                    <Button
                      variant={tags.includes(value as ContextTag) ? 'default' : 'outline'}
                      type="button"
                      key={value}
                      className={`choice ${tags.includes(value as ContextTag) ? 'active' : ''}`}
                      aria-pressed={tags.includes(value as ContextTag)}
                      onClick={() =>
                        setTags(
                          tags.includes(value as ContextTag)
                            ? tags.filter((t) => t !== value)
                            : [...tags, value as ContextTag],
                        )
                      }
                    >
                      {label}
                    </Button>
                  ))}
                </fieldset>
              </>
            )}
            {kind === 'post_run' && (
              <>
                <span className="eyebrow">AFTER YOUR RUN</span>
                <h2>Session RPE</h2>
                <p>How hard was the entire session, 0 = rest and 10 = maximal?</p>
                {!activityId && <p className="error-text">No run selected.</p>}
                {activityId && execution.isPending && <p role="status">Loading session…</p>}
                {execution.error && (
                  <p className="error-text" role="alert">
                    {execution.error.message}{' '}
                    <Button
                      variant="outline"
                      type="button"
                      onClick={() => {
                        void execution.refetch()
                      }}
                    >
                      Try again
                    </Button>
                  </p>
                )}
                <div className="choice-grid rpe-grid" role="group" aria-label="Session RPE scale">
                  {Array.from({ length: 11 }, (_, n) => (
                    <Button
                      variant={rpe === n ? 'default' : 'outline'}
                      type="button"
                      key={n}
                      className={`choice ${rpe === n ? 'active' : ''}`}
                      aria-pressed={rpe === n}
                      onClick={() => setRpe(n)}
                    >
                      {n}
                    </Button>
                  ))}
                </div>
                <small>0 = rest · 10 = maximal</small>
                {changed && (
                  <>
                    <label htmlFor="checkin-reason">What changed the session? (optional)</label>
                    <NativeSelect
                      id="checkin-reason"
                      value={reason}
                      onChange={(e) => setReason(e.target.value as ModificationReason | '')}
                    >
                      <option value="">No reason given</option>
                      {Object.entries(REASON_LABELS).map(([v, label]) => (
                        <option value={v} key={v}>
                          {label}
                        </option>
                      ))}
                    </NativeSelect>
                    <label htmlFor="checkin-reason-note">Reason note (optional)</label>
                    <Textarea
                      id="checkin-reason-note"
                      maxLength={1000}
                      value={reasonNote}
                      onChange={(e) => setReasonNote(e.target.value)}
                    />
                  </>
                )}
              </>
            )}
            <label htmlFor="checkin-note">
              {kind === 'post_run' ? 'Anything else? (optional)' : 'Note (optional)'}
            </label>
            <Textarea
              id="checkin-note"
              maxLength={1000}
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <Button
              type="submit"
              disabled={kind === 'post_run' && (rpe === null || !activityId || !execution.data)}
            >
              {mutation.isPending ? 'Saving…' : kind === 'exception' ? 'Save check-in' : 'Save'}
            </Button>
          </fieldset>
          {mutation.error && (
            <p className="error-text" role="alert">
              {mutation.error.message}
            </p>
          )}
        </form>
      )}
      <Button variant="link" onClick={close}>
        Cancel
      </Button>
    </Modal>
  )
}
