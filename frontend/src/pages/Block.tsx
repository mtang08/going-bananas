import { Card, Disclosure } from '../components/ui'
import { useQuery } from '@tanstack/react-query'
import { api, dateLabel, qk, RECIPE_LABELS, type BlockVersion, type CalendarView } from '../api'
import { QueryState } from '../components/QueryState'
import './TrainingDesign.css'
export function Block() {
  const active = useQuery({
    queryKey: qk.blocksActive,
    queryFn: () => api<BlockVersion | null>('/blocks/active'),
  })
  const calendar = useQuery({
    queryKey: qk.calendarView('head'),
    queryFn: () => api<CalendarView>('/calendar'),
  })
  const block = active.data?.data
  const history = useQuery({
    queryKey: ['v2', 'blocks', 'history', block?.block_uid],
    enabled: !!block,
    queryFn: () =>
      api<{
        items: BlockVersion[]
      }>(`/blocks/${encodeURIComponent(block!.block_uid)}/history`),
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
            <Card className="block-direction">
              <span className="eyebrow">CURRENT OBJECTIVE</span>
              <h2>{block.objective}</h2>
              <div className="direction-chips">
                <span>{block.status}</span>
                <span>Objective: {block.objective_status.replaceAll('_', ' ')}</span>
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
              <h3>Maintained qualities</h3>
              <div className="direction-chips">
                {block.maintained_qualities.length
                  ? block.maintained_qualities.map((value) => <span key={value}>{value}</span>)
                  : 'Not specified'}
              </div>
              <h3>Completion indicators to review</h3>
              <p className="fineprint">Review criteria; achievement has not been verified here.</p>
              <ul className="review-checklist">
                {block.completion_indicators.map((value) => (
                  <li key={value}>
                    <span aria-hidden="true">□</span>
                    {value}
                  </li>
                ))}
              </ul>
              <h3>Earlier review triggers</h3>
              <ul>
                {block.early_review_triggers.map((value) => (
                  <li key={value}>{value}</li>
                ))}
              </ul>
              <Disclosure className="training-disclosure">
                <summary>Why this block & session guidance</summary>
                <p>{block.rationale}</p>
                <h3>Eligible sessions</h3>
                <p>
                  {block.eligible_recipe_ids.map((id) => RECIPE_LABELS[id] || id).join(', ') ||
                    'Not specified'}
                </p>
                <h3>Constraints</h3>
                {block.constraints.length ? (
                  <ul>
                    {block.constraints.map((constraint, index) => (
                      <li key={index}>{constraint.text}</li>
                    ))}
                  </ul>
                ) : (
                  <p>Not specified</p>
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
                  <article className="block-history" key={version.id}>
                    <h3>
                      Version {version.version} · {version.status}
                    </h3>
                    <p>{version.objective}</p>
                    <p>{version.rationale}</p>
                    {version.proposal_id && (
                      <a href={`#proposal/${encodeURIComponent(version.proposal_id)}`}>
                        View reviewed proposal
                      </a>
                    )}
                  </article>
                ))}
              </QueryState>
            </Disclosure>
          </>
        )}
      </QueryState>
    </section>
  )
}
