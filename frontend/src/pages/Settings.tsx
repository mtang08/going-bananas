import { Badge, Button, Card, Input, NativeSelect } from '../components/ui'
import { useEffect, useState } from 'react'
import {
  keepPreviousData,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import { Database, Plus, RefreshCw } from 'lucide-react'
import {
  api,
  dateLabel,
  post,
  put,
  validDate,
  type Conflict,
  type ImportCount,
  type ImportRecord,
  type Profile,
  type SyncJob,
  type SyncStatus,
} from '../api'
import { Empty } from '../components/Empty'
import { QueryState } from '../components/QueryState'
import { stateLabel, useServer, type Unit } from '../components/shared'
const importDatasets = ['activities', 'sleep', 'hrv', 'resting_hr'] as const
function safeCount(value: unknown) {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
    ? String(value)
    : '—'
}
function ImportCounts({ counts }: { counts?: ImportCount }) {
  if (!counts) return null
  return (
    <small>
      Seen {safeCount(counts.seen)} · New revisions {safeCount(counts.new_revisions)} · Changed{' '}
      {safeCount(counts.changed)} · Rejected {safeCount(counts.rejected)}
    </small>
  )
}
function ImportSummary({ item }: { item: ImportRecord }) {
  const counters = item.counters
  const coverage = importDatasets
    .map((dataset) => ({ dataset, dates: counters?.datasets?.[dataset] }))
    .filter(
      (entry) =>
        entry.dates &&
        validDate(entry.dates.first_date || '') &&
        validDate(entry.dates.last_date || ''),
    )
  const preserved = Object.values(counters?.preserved_only || {}).reduce(
    (total, value) =>
      total + (typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : 0),
    0,
  )
  return (
    <div className="import-entry">
      <div className="import-title">
        <strong>{item.source_kind === 'garmin_export' ? 'Garmin export' : 'Local import'}</strong>
        <Badge className="status-chip">
          {['complete', 'succeeded', 'failed', 'running', 'queued', 'partial'].includes(item.status)
            ? stateLabel(item.status)
            : 'recorded'}
        </Badge>
      </div>
      <small>
        {item.finished_at && !Number.isNaN(Date.parse(item.finished_at))
          ? `Finished ${new Date(item.finished_at).toLocaleString()}`
          : item.started_at && !Number.isNaN(Date.parse(item.started_at))
            ? `Started ${new Date(item.started_at).toLocaleString()}`
            : 'Date unavailable'}
      </small>
      {counters?.activities && (
        <div className="import-dataset">
          <strong>Activities</strong>
          <ImportCounts counts={counters.activities} />
        </div>
      )}
      {importDatasets
        .filter((dataset) => dataset !== 'activities')
        .map(
          (dataset) =>
            counters?.recovery?.[dataset] && (
              <div className="import-dataset" key={dataset}>
                <strong>{dataset.replaceAll('_', ' ')}</strong>
                <ImportCounts counts={counters.recovery?.[dataset]} />
              </div>
            ),
        )}
      {preserved > 0 && (
        <small>
          {preserved} recovery entries were preserved without an observation. They do not count as
          zero values.
        </small>
      )}
      {item.status === 'partial' && (
        <small>
          Import incomplete: some records could not be used. Counts above show accepted and rejected
          records.
        </small>
      )}
      {coverage.length > 0 && (
        <div className="import-coverage">
          <strong>Observed date coverage</strong>
          {coverage.map(({ dataset, dates }) => (
            <small key={dataset}>
              {dataset.replaceAll('_', ' ')}:{' '}
              {dateLabel(dates!.first_date!, { month: 'short', day: 'numeric', year: 'numeric' })} –{' '}
              {dateLabel(dates!.last_date!, { month: 'short', day: 'numeric', year: 'numeric' })}
              {dates!.fully_enumerated === false
                ? ' · Observed dates only; completeness unverified'
                : ''}
            </small>
          ))}
        </div>
      )}
    </div>
  )
}
const weekdayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
function ScheduleDayPicker({
  label,
  days,
  onToggle,
}: {
  label: string
  days: number[]
  onToggle: (day: number) => void
}) {
  return (
    <div className="field">
      <strong>{label}</strong>
      <div className="weekday-picker">
        {weekdayNames.map((name, i) => (
          <label key={name}>
            <input type="checkbox" checked={days.includes(i)} onChange={() => onToggle(i)} />
            {name}
          </label>
        ))}
      </div>
    </div>
  )
}
export function Settings({
  unit,
  setUnit,
  onCheckin,
}: {
  unit: Unit
  setUnit: (u: Unit) => void
  onCheckin: () => void
}) {
  const [pendingJobIds, setPendingJobIds] = useState<string[]>([])
  const [syncOutcome, setSyncOutcome] = useState<string | null>(null)
  const profile = useServer<Profile>(['profile'], '/profile'),
    sync = useQuery({
      queryKey: ['sync'],
      queryFn: () => api<SyncStatus>('/sync/status'),
      placeholderData: keepPreviousData,
      refetchInterval: pendingJobIds.length ? 2000 : false,
    }),
    conflicts = useServer<{
      items: Conflict[]
    }>(['conflicts'], '/conflicts'),
    imports = useServer<{
      items: ImportRecord[]
    }>(['imports'], '/imports')
  const [timezone, setTimezone] = useState(''),
    [anchor, setAnchor] = useState<string | null>(null),
    [confirmAnchor, setConfirmAnchor] = useState<boolean | null>(null),
    [confirmStrength, setConfirmStrength] = useState<boolean | null>(null),
    [strengthDays, setStrengthDays] = useState<number[] | null>(null)
  const [scheduleMode, setScheduleMode] = useState<'weekly' | 'alternating' | null>(null),
    [weekAStart, setWeekAStart] = useState<string | null>(null),
    [weekADays, setWeekADays] = useState<number[] | null>(null),
    [weekBDays, setWeekBDays] = useState<number[] | null>(null)
  const [mobilityADays, setMobilityADays] = useState<number[] | null>(null),
    [mobilityBDays, setMobilityBDays] = useState<number[] | null>(null),
    [optionalMobilityDays, setOptionalMobilityDays] = useState<number[] | null>(null)
  const qc = useQueryClient()
  const syncNow = useMutation({
    mutationFn: () =>
      post<{
        jobs: SyncJob[]
      }>('/sync', {}),
    onSuccess: (result) => {
      setSyncOutcome(null)
      setPendingJobIds(result.data.jobs.map((job) => job.id))
      void qc.invalidateQueries({ queryKey: ['sync'] })
    },
  })
  const jobs = useQueries({
    queries: pendingJobIds.map((id) => ({
      queryKey: ['sync-job', id],
      queryFn: () => api<SyncJob>(`/sync/jobs/${id}`),
      refetchInterval: 2000,
    })),
  })
  const finished =
    pendingJobIds.length > 0 &&
    jobs.every((job) => job.data && ['succeeded', 'failed'].includes(job.data.data.status))
  useEffect(() => {
    if (!finished) return
    setSyncOutcome(
      jobs.some((job) => job.data?.data.status === 'failed')
        ? 'One or more datasets failed. Check the dataset status and retry.'
        : 'Sync finished. Analytics have been refreshed.',
    )
    void qc.invalidateQueries({ queryKey: ['sync'] })
    void qc.invalidateQueries({ queryKey: ['summary'] })
    void qc.invalidateQueries({ queryKey: ['weekly-recap'] })
    void qc.invalidateQueries({ queryKey: ['recovery'] })
    void qc.invalidateQueries({ queryKey: ['activities'] })
    setPendingJobIds([])
  }, [finished, qc, jobs])
  const save = useMutation({
    mutationFn: () =>
      put<Profile>('/profile', {
        expected_version: profile.data?.data.version || 0,
        timezone: timezone || profile.data?.data.timezone || 'America/New_York',
        cycle_anchor: anchor === null ? profile.data?.data.cycle_anchor || null : anchor || null,
        anchor_confirmed: confirmAnchor ?? profile.data?.data.anchor_confirmed ?? false,
        strength_days_confirmed:
          confirmStrength ?? profile.data?.data.strength_days_confirmed ?? false,
        scheduled_strength_days: strengthDays ?? profile.data?.data.scheduled_strength_days ?? [],
        strength_schedule_mode:
          scheduleMode ?? profile.data?.data.strength_schedule_mode ?? 'weekly',
        strength_week_a_start:
          weekAStart === null
            ? (profile.data?.data.strength_week_a_start ?? null)
            : weekAStart || null,
        strength_week_a_days: weekADays ?? profile.data?.data.strength_week_a_days ?? [],
        strength_week_b_days: weekBDays ?? profile.data?.data.strength_week_b_days ?? [],
        mobility_week_a_days: mobilityADays ?? profile.data?.data.mobility_week_a_days ?? [],
        mobility_week_b_days: mobilityBDays ?? profile.data?.data.mobility_week_b_days ?? [],
        mobility_optional_days:
          optionalMobilityDays ?? profile.data?.data.mobility_optional_days ?? [],
        facts: profile.data?.data.facts || {},
        preferences: profile.data?.data.preferences || {},
        unknowns: profile.data?.data.unknowns || [],
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['profile'] })
      qc.invalidateQueries({ queryKey: ['plans'] })
      qc.invalidateQueries({ queryKey: ['coach'] })
      qc.invalidateQueries({ queryKey: ['summary'] })
      qc.invalidateQueries({ queryKey: ['weekly-recap'] })
    },
  })
  const p = profile.data?.data
  const chosenAnchor = anchor ?? p?.cycle_anchor ?? ''
  const chosenTimezone = timezone || p?.timezone || 'America/New_York'
  const days = strengthDays ?? p?.scheduled_strength_days ?? []
  const mode = scheduleMode ?? p?.strength_schedule_mode ?? 'weekly'
  const aDays = weekADays ?? p?.strength_week_a_days ?? [],
    bDays = weekBDays ?? p?.strength_week_b_days ?? []
  const mobilityA = mobilityADays ?? p?.mobility_week_a_days ?? [],
    mobilityB = mobilityBDays ?? p?.mobility_week_b_days ?? [],
    optionalMobility = optionalMobilityDays ?? p?.mobility_optional_days ?? []
  const chosenWeekAStart = weekAStart ?? p?.strength_week_a_start ?? ''
  const confirmedStrength = confirmStrength ?? p?.strength_days_confirmed ?? false
  const scheduleError =
    confirmedStrength &&
    (mode === 'weekly'
      ? days.length !== 2
      : aDays.length !== 2 ||
        bDays.length !== 2 ||
        !validDate(chosenWeekAStart) ||
        new Date(`${chosenWeekAStart}T12:00:00Z`).getUTCDay() !== 1)
  const toggleDay = (value: number, items: number[], set: (value: number[]) => void) => {
    set(
      items.includes(value)
        ? items.filter((day) => day !== value)
        : [...items, value].sort((a, b) => a - b),
    )
    setConfirmStrength(false)
  }
  return (
    <section className="page-content">
      <div className="page-heading">
        <div>
          <div className="eyebrow">LOCAL DATA</div>
          <h1>Data & settings.</h1>
          <p>Know what is available, what is missing, and how your calendar is set.</p>
        </div>
        <Button onClick={onCheckin}>
          <Plus size={18} /> Record check-in
        </Button>
      </div>
      <div className="grid halves">
        <Card>
          <div className="panel-head">
            <div>
              <h2>Profile & cycle</h2>
              <p>Versioned settings · changes apply prospectively</p>
            </div>
          </div>
          <QueryState loading={profile.isPending} error={profile.error} stale={!!profile.data}>
            {p && (
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  save.mutate()
                }}
              >
                <div className="field">
                  <label htmlFor="timezone">Display timezone</label>
                  <Input
                    id="timezone"
                    value={chosenTimezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    required
                  />
                  <small>Use an IANA name, for example America/New_York.</small>
                </div>
                <div className="field">
                  <label htmlFor="anchor">Run parity anchor</label>
                  <Input
                    id="anchor"
                    type="date"
                    value={chosenAnchor}
                    onChange={(e) => {
                      setAnchor(e.target.value)
                      setConfirmAnchor(false)
                    }}
                  />
                  <small>
                    One confirmed run opportunity date sets every-other-day parity. It is
                    independent of Week A/B strength.
                  </small>
                </div>
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={confirmAnchor ?? p.anchor_confirmed}
                    onChange={(e) => setConfirmAnchor(e.target.checked)}
                  />{' '}
                  I confirm this run anchor date
                </label>
                <div className="field">
                  <label htmlFor="schedule-mode">Strength schedule</label>
                  <NativeSelect
                    id="schedule-mode"
                    value={mode}
                    onChange={(e) => {
                      setScheduleMode(e.target.value as 'weekly' | 'alternating')
                      setConfirmStrength(false)
                    }}
                  >
                    <option value="weekly">Same two days every week</option>
                    <option value="alternating">Alternating Week A / Week B</option>
                  </NativeSelect>
                  <small>
                    Choose two full-body strength days in each week. The pattern repeats
                    automatically; no weekly plan draft is needed.
                  </small>
                </div>
                {mode === 'weekly' ? (
                  <ScheduleDayPicker
                    label="Full-body strength · every week"
                    days={days}
                    onToggle={(day) => toggleDay(day, days, setStrengthDays)}
                  />
                ) : (
                  <>
                    <div className="field">
                      <label htmlFor="week-a-start">Week A Monday</label>
                      <Input
                        id="week-a-start"
                        type="date"
                        value={chosenWeekAStart}
                        onChange={(e) => {
                          setWeekAStart(e.target.value)
                          setConfirmStrength(false)
                        }}
                      />
                      <small>
                        These seven dates use Week A, the next seven use Week B, then the 14-day
                        pattern repeats.
                      </small>
                    </div>
                    <div className="schedule-week">
                      <h3>Week A</h3>
                      <p>Starting on the reference Monday.</p>
                      <ScheduleDayPicker
                        label="Full-body strength · two days"
                        days={aDays}
                        onToggle={(day) => toggleDay(day, aDays, setWeekADays)}
                      />
                      <ScheduleDayPicker
                        label="Required gym mobility"
                        days={mobilityA}
                        onToggle={(day) => toggleDay(day, mobilityA, setMobilityADays)}
                      />
                    </div>
                    <div className="schedule-week">
                      <h3>Week B</h3>
                      <p>The following Monday through Sunday.</p>
                      <ScheduleDayPicker
                        label="Full-body strength · two days"
                        days={bDays}
                        onToggle={(day) => toggleDay(day, bDays, setWeekBDays)}
                      />
                      <ScheduleDayPicker
                        label="Required gym mobility"
                        days={mobilityB}
                        onToggle={(day) => toggleDay(day, mobilityB, setMobilityBDays)}
                      />
                    </div>
                    <ScheduleDayPicker
                      label="Optional mobility · both weeks"
                      days={optionalMobility}
                      onToggle={(day) => toggleDay(day, optionalMobility, setOptionalMobilityDays)}
                    />
                  </>
                )}
                <label className="checkbox">
                  <input
                    type="checkbox"
                    checked={confirmedStrength}
                    onChange={(e) => setConfirmStrength(e.target.checked)}
                  />{' '}
                  I confirm this repeating strength and mobility pattern
                </label>
                {scheduleError && (
                  <p className="error-text" role="alert">
                    Choose exactly two full-body strength days per week
                    {mode === 'alternating' ? ' and a valid Week A Monday' : ''} before confirming.
                  </p>
                )}
                {save.error && (
                  <p className="error-text" role="alert">
                    {save.error.message}
                  </p>
                )}
                {save.isSuccess && (
                  <p className="success-text">
                    Profile saved as a new version. Coach and the cycle calendar will use this
                    repeating pattern.
                  </p>
                )}
                <Button type="submit" disabled={save.isPending || scheduleError}>
                  Save profile
                </Button>
              </form>
            )}
          </QueryState>
        </Card>
        <div className="side-stack">
          <Card>
            <div className="panel-head">
              <div>
                <h2>Display units</h2>
                <p>Storage and server metrics stay in SI units</p>
              </div>
            </div>
            <div className="segmented">
              <Button
                variant="ghost"
                className={
                  unit === 'mi'
                    ? 'active bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground'
                }
                onClick={() => setUnit('mi')}
              >
                Miles
              </Button>
              <Button
                variant="ghost"
                className={
                  unit === 'km'
                    ? 'active bg-card text-foreground shadow-sm'
                    : 'text-muted-foreground'
                }
                onClick={() => setUnit('km')}
              >
                Kilometers
              </Button>
            </div>
          </Card>
          <Card>
            <div className="panel-head">
              <div>
                <h2>Import & backup</h2>
                <p>Handled by the local command line</p>
              </div>
              <Database size={20} />
            </div>
            <p>
              Use Sync now or the documented local CLI for Garmin data. The browser does not read
              archive files or keys.
            </p>
            <p>
              Strong CSV history is available in the Strength view. Import later exports to refresh
              it; absent entries never imply missed lifting. Private backups contain the database,
              raw imports, and profile configuration. Restore into a new target before selecting it.
            </p>
            <code className="command">make backup</code>
          </Card>
        </div>
      </div>
      <Card className="import-panel">
        <div className="panel-head">
          <div>
            <h2>Historical imports</h2>
            <p>Local import results and observed date coverage</p>
          </div>
          <Database size={19} />
        </div>
        <QueryState
          loading={imports.isPending}
          error={imports.error}
          stale={!!imports.data}
          retry={() => imports.refetch()}
        >
          {imports.data &&
            (imports.data.data.items.length ? (
              <div className="import-list">
                {imports.data.data.items.map((item) => (
                  <ImportSummary key={item.id} item={item} />
                ))}
              </div>
            ) : (
              <Empty
                title="No historical imports yet"
                text="Completed local archive imports will appear here."
              />
            ))}
        </QueryState>
      </Card>
      <div className="grid halves">
        <Card>
          <div className="panel-head">
            <div>
              <h2>Sync status</h2>
              <p>Freshness is independent for each dataset</p>
            </div>
            <RefreshCw size={19} />
          </div>
          <QueryState
            loading={sync.isPending}
            error={sync.error}
            stale={!!sync.data}
            retry={() => sync.refetch()}
          >
            {sync.data && (
              <>
                {profile.data?.mode === 'real' && (
                  <div className="sync-action">
                    <Button
                      onClick={() => syncNow.mutate()}
                      disabled={syncNow.isPending || pendingJobIds.length > 0}
                    >
                      <RefreshCw size={15} />{' '}
                      {pendingJobIds.length ? 'Sync in progress' : 'Sync now'}
                    </Button>
                    <small>Requests recent activities and available recovery datasets.</small>
                  </div>
                )}
                {syncNow.error && (
                  <p className="error-text" role="alert">
                    {syncNow.error.message}
                  </p>
                )}
                {syncOutcome && (
                  <p
                    className={syncOutcome.startsWith('One') ? 'error-text' : 'success-text'}
                    role="status"
                  >
                    {syncOutcome}
                  </p>
                )}
                {pendingJobIds.length > 0 && (
                  <div className="sync-jobs">
                    {jobs.map((job, i) => (
                      <small key={pendingJobIds[i]}>
                        {job.data?.data.dataset || 'Dataset'}:{' '}
                        {stateLabel(job.data?.data.status || 'queued')}
                      </small>
                    ))}
                  </div>
                )}
                {pendingJobIds.length === 0 && !!sync.data.data.active_jobs?.length && (
                  <div className="sync-jobs">
                    {sync.data.data.active_jobs.map((job) => (
                      <small key={job.id}>
                        {job.dataset}: {stateLabel(job.status)}
                      </small>
                    ))}
                  </div>
                )}
                {Array.isArray(sync.data.data.datasets) && sync.data.data.datasets.length ? (
                  <div className="sync-list">
                    {sync.data.data.datasets.map((d) => (
                      <div className="sync-row" key={d.dataset}>
                        <strong>{d.dataset.replaceAll('_', ' ')}</strong>
                        <Badge className="status-chip">{stateLabel(d.status)}</Badge>
                        <small>
                          Last success:{' '}
                          {d.last_success_at
                            ? new Date(d.last_success_at).toLocaleString()
                            : 'never'}{' '}
                          · Newest observation:{' '}
                          {d.newest_observation_at
                            ? dateLabel(d.newest_observation_at.slice(0, 10))
                            : 'unknown'}
                        </small>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty title="No sync status yet" text="No dataset has a completed local sync." />
                )}
              </>
            )}
          </QueryState>
        </Card>
        <Card>
          <div className="panel-head">
            <div>
              <h2>Resolution queue</h2>
              <p>Potential duplicates need explicit review</p>
            </div>
          </div>
          <QueryState
            loading={conflicts.isPending}
            error={conflicts.error}
            stale={!!conflicts.data}
          >
            {conflicts.data &&
              (conflicts.data.data.items.length ? (
                <div className="conflict-list">
                  {conflicts.data.data.items.map((c) => (
                    <ConflictRow key={c.id} conflict={c} />
                  ))}
                </div>
              ) : (
                <Empty
                  title="No open conflicts"
                  text="Uncertain matches will appear here for review."
                />
              ))}
          </QueryState>
        </Card>
      </div>
    </section>
  )
}
function ConflictRow({ conflict }: { conflict: Conflict }) {
  const qc = useQueryClient(),
    [canonical, setCanonical] = useState(conflict.activity_ids?.[0] || '')
  const resolve = useMutation({
    mutationFn: (resolution: 'merge' | 'keep_separate' | 'reverse') =>
      post(`/conflicts/${conflict.id}/resolve`, {
        resolution,
        canonical_activity_id: resolution === 'merge' ? canonical : undefined,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['conflicts'] }),
  })
  return (
    <div className="conflict-row">
      <strong>{conflict.kind.replaceAll('_', ' ')}</strong>
      <small>
        {conflict.status} · {conflict.activity_ids?.length || 0} activities
        {conflict.manual_session_id ? ' · manual session' : ''}
      </small>
      {conflict.status === 'open' ? (
        <div className="conflict-actions">
          {conflict.activity_ids?.length > 0 && (
            <NativeSelect
              aria-label="Canonical activity"
              value={canonical}
              onChange={(e) => setCanonical(e.target.value)}
            >
              {conflict.activity_ids.map((id) => (
                <option key={id} value={id}>
                  {id.slice(0, 8)}
                </option>
              ))}
            </NativeSelect>
          )}
          <Button
            onClick={() => resolve.mutate('merge')}
            disabled={!canonical || resolve.isPending}
          >
            Merge
          </Button>
          <Button
            onClick={() => resolve.mutate('keep_separate')}
            disabled={resolve.isPending}
            variant="outline"
          >
            Keep separate
          </Button>
        </div>
      ) : (
        <Button
          onClick={() => resolve.mutate('reverse')}
          disabled={resolve.isPending}
          variant="link"
        >
          Reverse decision
        </Button>
      )}
      {resolve.error && <small className="error-text">{resolve.error.message}</small>}
    </div>
  )
}
