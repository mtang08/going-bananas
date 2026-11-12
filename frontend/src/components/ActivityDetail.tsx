import { Button, Disclosure, NativeSelect } from './ui'
import { Modal } from './Modal'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { dateLabel, distance, duration, pace, patch, type Activity } from '../api'
import { QueryState } from './QueryState'
import { stateLabel, useServer, type Unit } from './shared'
export function ActivityDetail({ id, unit, close }: { id: string; unit: Unit; close: () => void }) {
  const qc = useQueryClient(),
    detail = useServer<Activity>(['activity', id], `/activities/${encodeURIComponent(id)}`)
  const [label, setLabel] = useState<string | null>(null)
  const chosenLabel =
    label ?? detail.data?.data.annotations?.workout_label ?? detail.data?.data.workout_label ?? ''
  const save = useMutation({
    mutationFn: () =>
      patch<Activity>(`/activities/${encodeURIComponent(id)}/annotations`, {
        expected_version: detail.data?.data.annotations?.version || 0,
        workout_label: chosenLabel || null,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['activity', id] })
      qc.invalidateQueries({ queryKey: ['activities'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
    },
  })
  const a = detail.data?.data
  return (
    <Modal label="Activity detail" className="detail-modal sm:max-w-4xl" close={close}>
      <div className="eyebrow">ACTIVITY DETAIL</div>
      <h2>{a?.sport.replaceAll('_', ' ') || 'Loading activity'}</h2>
      <QueryState loading={detail.isPending} error={detail.error} stale={!!detail.data}>
        {a && (
          <>
            <p className="muted-text">
              {dateLabel(a.local_date, {
                weekday: 'long',
                month: 'long',
                day: 'numeric',
                year: 'numeric',
              })}{' '}
              ·{' '}
              {new Date(a.start_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}
            </p>
            <div className="detail-stats">
              <div>
                <small>Distance</small>
                <strong>{distance(a.distance_m, unit)}</strong>
              </div>
              <div>
                <small>Elapsed</small>
                <strong>{duration(a.elapsed_s)}</strong>
              </div>
              <div>
                <small>Moving</small>
                <strong>{duration(a.moving_s)}</strong>
              </div>
              <div>
                <small>Moving pace</small>
                <strong>{pace(a.moving_pace_s_per_km, unit)}</strong>
              </div>
            </div>
            <div className="field">
              <label htmlFor="workout-label">Workout label</label>
              <div className="inline-form">
                <NativeSelect
                  id="workout-label"
                  value={chosenLabel}
                  onChange={(e) => setLabel(e.target.value)}
                >
                  <option value="">Unknown</option>
                  <option value="easy">Easy</option>
                  <option value="quality">Quality</option>
                  <option value="long">Long</option>
                  <option value="other">Other</option>
                </NativeSelect>
                <Button onClick={() => save.mutate()} disabled={save.isPending}>
                  Save label
                </Button>
              </div>
              {save.error && <small className="error-text">{save.error.message}</small>}
              {save.isSuccess && <small>Saved.</small>}
            </div>
            {a.classification && a.sport === 'running' && (
              <Disclosure className="notice muted">
                <summary>
                  {a.classification.label_source === 'heuristic'
                    ? `Auto: ${a.classification.effective_label}`
                    : a.classification.label_source === 'manual'
                      ? `Manual: ${a.classification.effective_label}`
                      : a.classification.label_source === 'source'
                        ? `Source: ${a.classification.effective_label}`
                        : 'Run type unknown'}{' '}
                  · details
                </summary>
                <p>
                  {a.classification.confidence} confidence ·{' '}
                  {a.classification.method.replaceAll('_', ' ')}
                </p>
                {a.classification.reasons.length > 0 && (
                  <ul>
                    {a.classification.reasons.map((reason, i) => (
                      <li key={i}>{reason}</li>
                    ))}
                  </ul>
                )}
              </Disclosure>
            )}
            <div className="provenance">
              <h3>Source & provenance</h3>
              <p>
                Resolution: {stateLabel(a.resolution_state)} · Source: {a.source || 'unknown'}
              </p>
              {a.provenance && (
                <dl>
                  {Object.entries(a.provenance).map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replaceAll('_', ' ')}</dt>
                      <dd>
                        {typeof value === 'string' || typeof value === 'number'
                          ? String(value)
                          : 'Recorded'}
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </div>
          </>
        )}
      </QueryState>
    </Modal>
  )
}
