import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { put } from '../../api/client'
import { qk, invalidateKeys } from '../../api/queryKeys'
import type { Profile, RunningRestriction } from '../../api/types/profile'
import { Button, Card, Input, Textarea } from '../../components/ui'
import { ErrorText, Select, profileBody } from './shared'

const restrictionKey = 'running_restriction'
const legacyKeys = ['clinical_restriction', 'clinician_restriction', 'clinical_restriction_active']
const metersPerUnit = { m: 1, km: 1000, mi: 1609.344 }

function legacyRestriction(facts: Profile['facts']) {
  for (const key of legacyKeys.slice(0, 2)) {
    const value = facts[key]
    if (
      typeof value === 'string' &&
      !['', 'none', 'unknown'].includes(value.trim().toLowerCase())
    ) {
      return value
    }
  }
  return facts.clinical_restriction_active ? 'Restriction recorded without wording.' : null
}

export function RunningLimits({ profile, today }: { profile: Profile; today: string }) {
  const qc = useQueryClient()
  const current = profile.facts[restrictionKey] as RunningRestriction | null | undefined
  const legacy = legacyRestriction(profile.facts)
  const [starts, setStarts] = useState(current?.starts_on ?? today)
  const [ends, setEnds] = useState(current?.ends_on ?? '')
  const [review, setReview] = useState(current?.review_on ?? '')
  const [paused, setPaused] = useState(current?.pause_running ?? false)
  const [noQuality, setNoQuality] = useState(current?.no_quality ?? false)
  const [distance, setDistance] = useState(current?.max_distance_m?.toString() ?? '')
  const [unit, setUnit] = useState<keyof typeof metersPerUnit>('m')
  const [minutes, setMinutes] = useState(
    current?.max_duration_s ? String(current.max_duration_s / 60) : '',
  )
  const [source, setSource] = useState(current?.source ?? '')
  const [wording, setWording] = useState(current?.wording ?? '')
  const save = useMutation({
    mutationFn: (facts: Profile['facts']) => put('/profile', { ...profileBody(profile), facts }),
    onSuccess: () => invalidateKeys(qc, [qk.profile, qk.calendar, qk.proposals]),
  })
  const maxDistance = distance === '' ? null : Math.floor(Number(distance) * metersPerUnit[unit])
  const maxDuration = minutes === '' ? null : Math.floor(Number(minutes) * 60 + 1e-9)
  const canSave =
    !!starts &&
    (!ends || ends >= starts) &&
    (!review || review >= starts) &&
    !!source.trim() &&
    (paused || noQuality || !!maxDistance || !!maxDuration) &&
    (maxDistance === null || maxDistance > 0) &&
    (maxDuration === null || maxDuration > 0)
  const restriction: RunningRestriction = {
    starts_on: starts,
    ends_on: ends || null,
    review_on: review || null,
    pause_running: paused,
    no_quality: noQuality,
    max_distance_m: maxDistance,
    max_duration_s: maxDuration,
    source: source.trim(),
    wording: wording.trim() || null,
  }

  const clear = (keys: string[]) =>
    save.mutate(
      Object.fromEntries(Object.entries(profile.facts).filter(([key]) => !keys.includes(key))),
    )

  return (
    <Card id="running-limits">
      <h2>Running limits</h2>
      {current && (
        <p role="status">
          {current.ends_on && today > current.ends_on
            ? 'The recorded end date has passed.'
            : today < current.starts_on
              ? 'The saved running limits are scheduled.'
              : !current.ends_on && current.review_on && today >= current.review_on
                ? 'Review is due. Confirm updated limits or clear them once the restriction ends.'
                : 'The saved running limits are in effect.'}
        </p>
      )}
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault()
          if (canSave) save.mutate({ ...profile.facts, [restrictionKey]: restriction })
        }}
      >
        <div className="field">
          <label htmlFor="run-limit-start">First restricted day</label>
          <Input
            id="run-limit-start"
            type="date"
            required
            value={starts}
            onChange={(e) => setStarts(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="run-limit-end">Last restricted day, if confirmed</label>
          <Input
            id="run-limit-end"
            type="date"
            min={starts}
            value={ends}
            onChange={(e) => setEnds(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="run-limit-review">Review date</label>
          <Input
            id="run-limit-review"
            type="date"
            min={starts}
            value={review}
            onChange={(e) => setReview(e.target.value)}
          />
          <small>
            Without a confirmed end date, the limit stays in effect after the review date.
          </small>
        </div>
        <div className="space-y-1">
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={paused} onChange={(e) => setPaused(e.target.checked)} />
            Pause running
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={noQuality}
              onChange={(e) => setNoQuality(e.target.checked)}
            />
            No quality sessions
          </label>
        </div>
        <div className="field">
          <label htmlFor="run-limit-distance">Maximum distance per run</label>
          <Input
            id="run-limit-distance"
            type="number"
            min={0}
            step="any"
            value={distance}
            onChange={(e) => setDistance(e.target.value)}
          />
        </div>
        <div className="field">
          <Select
            id="run-limit-unit"
            label="Distance unit"
            value={unit}
            options={{ m: 'Meters', km: 'Kilometers', mi: 'Miles' }}
            onChange={(value) => setUnit(value as keyof typeof metersPerUnit)}
          />
        </div>
        <div className="field">
          <label htmlFor="run-limit-minutes">Maximum minutes per run</label>
          <Input
            id="run-limit-minutes"
            type="number"
            min={0}
            step="any"
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="run-limit-source">Who confirmed the limit?</label>
          <Input
            id="run-limit-source"
            required
            maxLength={120}
            value={source}
            onChange={(e) => setSource(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="run-limit-wording">Original instruction</label>
          <Textarea
            id="run-limit-wording"
            maxLength={1000}
            value={wording}
            onChange={(e) => setWording(e.target.value)}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="submit" disabled={!canSave || save.isPending}>
            {current ? 'Update running limits' : 'Save running limits'}
          </Button>
          {current && (
            <Button
              type="button"
              variant="outline"
              disabled={save.isPending}
              onClick={() => clear([restrictionKey])}
            >
              Clear dated running limits
            </Button>
          )}
        </div>
      </form>
      {legacy && (
        <div className="mt-4 space-y-2">
          <h3>Previously recorded restriction</h3>
          <p>{legacy}</p>
          <Button
            type="button"
            variant="outline"
            disabled={save.isPending}
            onClick={() => clear(legacyKeys)}
          >
            Clear previously recorded restriction
          </Button>
        </div>
      )}
      <ErrorText error={save.error} />
    </Card>
  )
}
