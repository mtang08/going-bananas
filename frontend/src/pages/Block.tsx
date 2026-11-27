import { INDICATOR_LABELS, LegacyText, SourceChips, WhyList } from '../components/CoachText'
import {
  Button,
  Card,
  Disclosure,
  NativeSelect,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../components/ui'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  RUN_SPORTS,
  type ActiveBlock,
  type BenchmarkRecord,
  type BlockVersion,
} from '../api/types/blocks'
import { addDays, dateLabel, fmtDistance, fmtDuration, fmtRpe, type Unit } from '../lib/format'
import { getCalendar, api, put, query } from '../api/client'
import { invalidateKeys, qk } from '../api/queryKeys'
import { RECIPE_LABELS } from '../api/types/calendar'
import type { Activity } from '../api/types/activity'
import { benchmarkStatusLabel, OUTCOME_LABELS } from '../coachLabels'
import { QueryState } from '../components/QueryState'
import { GoalRaceTimeline } from '../components/GoalRaceTimeline'
import './TrainingDesign.css'
export function Block({ unit = 'mi' }: { unit?: Unit }) {
  const active = useQuery({
    queryKey: qk.blocksActive,
    queryFn: () => api<ActiveBlock | null>('/blocks/active'),
  })
  const calendar = useQuery({
    queryKey: qk.calendarView('head'),
    queryFn: () => getCalendar(),
  })
  const block = active.data?.data
  const history = useQuery({
    queryKey: qk.blockHistory(block?.block_uid),
    enabled: !!block,
    queryFn: () =>
      api<{
        items: BlockVersion[]
      }>(`/blocks/${encodeURIComponent(block!.block_uid)}/history`),
  })
  const benchmarks = useQuery({
    queryKey: qk.blockBenchmarks,
    enabled: !!block,
    queryFn: () => api<{ items: BenchmarkRecord[] }>('/blocks/benchmarks'),
  })
  const qc = useQueryClient()
  const bm = block?.benchmark ?? null
  const status = block?.benchmark_status ?? null
  const latestLogged = (benchmarks.data?.data.items ?? []).find((item) => item.local_date)
  const currentIsLatest =
    status?.status === 'completed' &&
    !!status.local_date &&
    (!latestLogged?.local_date || status.local_date >= latestLogged.local_date)
  const runStart = bm ? addDays(bm.planned_date, -7) : ''
  const runEnd = block ? addDays(block.review_date, 7) : ''
  const runs = useQuery({
    queryKey: qk.activityRuns(runStart, runEnd),
    enabled: Boolean(bm && block),
    queryFn: () =>
      api<{ items: Activity[] }>(
        `/activities${query({ start_date: runStart, end_date: runEnd, limit: 200 })}`,
      ),
  })
  const runOptions = (runs.data?.data?.items ?? []).filter((a) => RUN_SPORTS.includes(a.sport))
  const choose = useMutation({
    mutationFn: (activityId: string | null) =>
      put<unknown>(`/blocks/${encodeURIComponent(block!.block_uid)}/benchmark-activity`, {
        activity_id: activityId,
      }),
    onSuccess: () => invalidateKeys(qc, [qk.blocks, qk.exceptions]),
  })
  const days = (a: string, b: string) =>
    Math.floor((Date.parse(`${a}T12:00:00Z`) - Date.parse(`${b}T12:00:00Z`)) / 86400000)
  const today = calendar.data?.data.today
  return (
    <section className="page-content block-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">TRAINING DIRECTION</span>
          <h1>Training block</h1>
        </div>
        <a href="#calendar">Calendar</a>
      </div>
      <QueryState
        loading={active.isPending}
        error={active.error}
        retry={() => {
          void active.refetch()
        }}
      >
        {block === null && (
          <Card>
            <h2>No active training block</h2>
            <p>
              Establish your next objective with the coach during a Sunday review or block review.
            </p>
            <a href="#guide">How to review with the coach</a>
          </Card>
        )}
        {block && (
          <>
            <GoalRaceTimeline block={block} today={today} unit={unit} />
            <Card className="block-direction">
              <span className="eyebrow">CURRENT OBJECTIVE</span>
              <h2>{block.objective}</h2>
              <div className="direction-chips">
                <span>{block.status}</span>
                <span>Progression: {block.progression_dimension.replaceAll('_', ' ')}</span>
              </div>
              {today ? (
                <>
                  <ol className="block-clock" aria-label="Block elapsed time">
                    <li>
                      <small>Start</small>
                      <strong>{dateLabel(block.start_date)}</strong>
                    </li>
                    <li className="clock-today">
                      <small>Today</small>
                      <strong>{dateLabel(today)}</strong>
                      <span>
                        {days(today, block.start_date) < 0
                          ? `Starts in ${-days(today, block.start_date)} days`
                          : `${days(today, block.start_date)} days elapsed`}
                      </span>
                    </li>
                    <li>
                      <small>Review</small>
                      <strong>{dateLabel(block.review_date)}</strong>
                      <span>
                        {days(today, block.review_date) > 0
                          ? `Review overdue · ${days(today, block.review_date)} days`
                          : days(today, block.review_date) === 0
                            ? 'Review due today'
                            : `Review in ${-days(today, block.review_date)} days`}
                      </span>
                    </li>
                  </ol>
                  <p className="fineprint">
                    Elapsed time tracks the review schedule. It does not measure objective
                    completion.
                  </p>
                </>
              ) : (
                <p>
                  Start {dateLabel(block.start_date)} · Review {dateLabel(block.review_date)} ·
                  Today’s date unavailable
                </p>
              )}
              {block.early_review_triggers.length > 0 && (
                <p className="block-review-early">
                  <strong>Review early if:</strong>{' '}
                  {block.early_review_triggers.map((value, index) => (
                    <span key={index}>
                      {index > 0 && ' · '}
                      {value}
                    </span>
                  ))}
                </p>
              )}
              {block.maintained_qualities.length > 0 && (
                <div className="block-maintains">
                  <strong>Maintains:</strong>
                  <div className="direction-chips">
                    {block.maintained_qualities.map((value) => (
                      <span key={value}>{value}</span>
                    ))}
                  </div>
                </div>
              )}
              {(block.why.length > 0 || block.sources.length > 0) && (
                <Disclosure className="training-disclosure">
                  <summary>Why this block</summary>
                  <WhyList items={block.why} />
                  <SourceChips sources={block.sources} />
                </Disclosure>
              )}
              {(block.constraints.length > 0 || block.non_goals.length > 0) && (
                <Disclosure className="training-disclosure">
                  <summary>Constraints and out of scope</summary>
                  {block.constraints.length > 0 && (
                    <>
                      <h3>Constraints</h3>
                      <ul>
                        {block.constraints.map((constraint, index) => (
                          <li key={index}>{constraint.text}</li>
                        ))}
                      </ul>
                    </>
                  )}
                  {block.non_goals.length > 0 && (
                    <>
                      <h3>Outside this block's focus</h3>
                      <ul>
                        {block.non_goals.map((value) => (
                          <li key={value}>{value}</li>
                        ))}
                      </ul>
                    </>
                  )}
                </Disclosure>
              )}
              {block.eligible_recipe_ids.length > 0 && (
                <Disclosure className="training-disclosure">
                  <summary>Eligible sessions</summary>
                  <p>{block.eligible_recipe_ids.map((id) => RECIPE_LABELS[id] || id).join(', ')}</p>
                </Disclosure>
              )}
              <LegacyText text={block.legacy_text} />
            </Card>
            <Card className="block-benchmark" data-testid="block-benchmark">
              <h2>Goal progress</h2>
              {block.objective_status === 'unresolved' ? (
                <p>Progress toward the goal is unknown; the block objective remains unresolved.</p>
              ) : (
                <p>
                  <strong>Last recorded block assessment: </strong>
                  {block.objective_status.replaceAll('_', ' ')} ·{' '}
                  {dateLabel(block.created_at.slice(0, 10))}. This assessment applies to the block
                  objective; it does not predict the goal race.
                </p>
              )}
              <p>
                <strong>Goal: </strong>
                {block.target_event
                  ? `${block.target_event.name} · ${dateLabel(block.target_event.event_date)}`
                  : block.objective}
              </p>
              <QueryState
                loading={benchmarks.isPending}
                error={benchmarks.error}
                stale={!!benchmarks.data}
                retry={() => void benchmarks.refetch()}
              >
                {(() => {
                  const latest = latestLogged
                  return currentIsLatest ? null : latest ? (
                    <p data-testid="latest-benchmark">
                      <strong>Latest logged benchmark: </strong>
                      {dateLabel(latest.local_date!)} · {latest.protocol} ·{' '}
                      {fmtDistance(latest.distance_m, unit)} · {fmtDuration(latest.result_s)}
                      {latest.outcome && <> · {OUTCOME_LABELS[latest.outcome]}</>}
                      {latest.compared_with && <> · Compared with: {latest.compared_with}</>}
                    </p>
                  ) : (
                    <p>No dated benchmark result logged yet.</p>
                  )
                })()}
              </QueryState>
              {block.indicators.length > 0 && (
                <section className="block-indicators">
                  <h3>Review this block by</h3>
                  <p className="fineprint">
                    Review criteria; current indicator values are not assessed here.
                  </p>
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Indicator</TableHead>
                        <TableHead>Progress when</TableHead>
                        <TableHead>Source</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {block.indicators.map((item, index) => (
                        <TableRow key={index}>
                          <TableCell>{item.label}</TableCell>
                          <TableCell>{item.progress_when}</TableCell>
                          <TableCell>{INDICATOR_LABELS[item.source]}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </section>
              )}
              {block.indicators.length === 0 && <p>No review indicators set for this block.</p>}
              <h3>Next check</h3>
              <p>Block review: {dateLabel(block.review_date)}</p>
              {!bm ? (
                <p>
                  No benchmark in this block. Its review judges the block's review criteria instead.
                  A block gets a benchmark when the last result is about 6 weeks old or a race falls
                  in it.
                </p>
              ) : (
                <>
                  <p>{bm.protocol}</p>
                  <dl>
                    <div>
                      <dt>Planned</dt>
                      <dd>{dateLabel(bm.planned_date)}</dd>
                    </div>
                    <div>
                      <dt>Progress if</dt>
                      <dd>{bm.progress_if}</dd>
                    </div>
                    <div>
                      <dt>Consolidate if</dt>
                      <dd>{bm.consolidate_if}</dd>
                    </div>
                    <div>
                      <dt>Status</dt>
                      <dd data-testid="benchmark-status">
                        {benchmarkStatusLabel(status, bm.planned_date)}
                      </dd>
                    </div>
                  </dl>
                  {status?.status === 'completed' && currentIsLatest && (
                    <p data-testid="benchmark-match">
                      <strong>Latest benchmark: </strong>
                      {status.local_date ? dateLabel(status.local_date) : 'Date missing'} ·{' '}
                      {fmtDistance(status.distance_m, unit)} · {fmtDuration(status.result_s)} · RPE{' '}
                      {fmtRpe(status.rpe)} ·{' '}
                      {status.match_method === 'manual' ? 'Chosen by you' : 'Matched automatically'}
                    </p>
                  )}
                  <QueryState
                    loading={runs.isPending}
                    error={runs.error}
                    stale={!!runs.data}
                    retry={() => void runs.refetch()}
                  >
                    <label htmlFor="benchmark-activity">Choose activity</label>
                    <NativeSelect
                      id="benchmark-activity"
                      disabled={choose.isPending}
                      value={status?.match_method === 'manual' ? (status.activity_id ?? '') : ''}
                      onChange={(e) => {
                        if (e.target.value) choose.mutate(e.target.value)
                      }}
                    >
                      <option value="">Choose a run</option>
                      {runOptions.map((run) => (
                        <option key={run.id} value={run.id}>
                          {dateLabel(run.local_date)} · {fmtDistance(run.distance_m, unit)}
                        </option>
                      ))}
                    </NativeSelect>
                  </QueryState>
                  {status?.match_method === 'manual' && (
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={choose.isPending}
                      onClick={() => choose.mutate(null)}
                    >
                      Use automatic match
                    </Button>
                  )}
                  {choose.error && (
                    <p className="error-text" role="alert">
                      {choose.error.message}
                    </p>
                  )}
                </>
              )}
            </Card>
            <Disclosure className="training-disclosure" variant="card">
              <summary>Block history</summary>
              <QueryState
                loading={history.isPending}
                error={history.error}
                retry={() => {
                  void history.refetch()
                }}
              >
                {history.data?.data.items.map((version) => (
                  <Disclosure className="block-history" key={version.id}>
                    <summary>
                      Version {version.version} · {version.status} · {version.objective}
                    </summary>
                    <WhyList items={version.why} />
                    <LegacyText text={version.legacy_text} />
                    {version.proposal_id && (
                      <a href={`#proposal/${encodeURIComponent(version.proposal_id)}`}>
                        View reviewed proposal
                      </a>
                    )}
                  </Disclosure>
                ))}
              </QueryState>
            </Disclosure>
          </>
        )}
      </QueryState>
    </section>
  )
}
