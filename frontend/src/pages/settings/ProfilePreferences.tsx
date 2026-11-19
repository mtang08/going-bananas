import { Button, Card, Input } from '../../components/ui'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { put, qk, invalidateKeys, WEEKDAY_LABELS, type Profile, type Unit } from '../../api'
import { ErrorText, Select, profileBody } from './shared'

export function ReviewDay({ profile }: { profile: Profile }) {
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
export function Preferences({
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
