import { Disclosure } from '../components/ui'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, qk, pageHref, type Profile, type CalendarView, type StrengthRoutine, type Unit } from '../api'
import { QueryState } from '../components/QueryState'
import { SyncCard } from '../components/SyncCard'
import { Goals } from './settings/Goals'
import { Events } from './settings/Events'
import { Anchors } from './settings/Anchors'
import { StrengthSchedule } from './settings/StrengthSchedule'
import { Routine } from './settings/strengthRoutine'
import { CalendarSetup } from './settings/CalendarSetup'
import { ReviewDay, Preferences } from './settings/ProfilePreferences'

export function PlanningSettings({
  unit,
  setUnit,
}: {
  unit: Unit
  setUnit: (unit: Unit) => void
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
    <section className="page-content space-y-5">
      <div className="page-heading">
        <h1>Settings</h1>
        <a href="#guide">User guide</a>
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
      <SyncCard />
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
          <>
            <div className="grid halves">
              {view.head === 0 ? (
                <CalendarSetup
                  key={`${p.version}:${r.version}`}
                  profile={p}
                  routine={r}
                  today={view.today}
                  onCreated={setCreated}
                />
              ) : (
                <Routine key={r.version} routine={r} onSaved={() => setRoutineSaved(true)} />
              )}
              <Disclosure
                variant="card"
                className="training-disclosure"
                id="strength-schedule"
                data-testid="strength-schedule"
              >
                <summary>Strength schedule (weekly or alternating)</summary>
                <StrengthSchedule key={p.version} profile={p} />
              </Disclosure>
              <Preferences key={p.version} profile={p} unit={unit} setUnit={setUnit} />
              <ReviewDay profile={p} />
              <Goals />
              <Events unit={unit} />
            </div>
            <Disclosure
              variant="card"
              className="training-disclosure"
              data-testid="anchors-disclosure"
            >
              <summary>Intensity anchors</summary>
              <Anchors unit={unit} today={view.today} timezone={p.timezone} />
            </Disclosure>
          </>
        )}
      </QueryState>
    </section>
  )
}
