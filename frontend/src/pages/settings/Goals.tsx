import { Button, Card, Input } from '../../components/ui'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, post, patchGoal } from '../../api/client'
import { qk, invalidateKeys } from '../../api/queryKeys'
import { HORIZON_LABELS, type Goal, type GoalHorizon } from '../../api/types/blocks'
import { QueryState } from '../../components/QueryState'
import { ErrorText, Select } from './shared'

export function Goals() {
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
        ? patchGoal(editing.id, {
            expected_version: editing.version,
            text: text.trim(),
            horizon,
            priority,
            status,
          })
        : post('/goals', { text: text.trim(), horizon, priority }),
    onSuccess: () => {
      invalidateKeys(qc, [qk.goals, qk.proposals])
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
