import type { ProposalDetail } from '../../api/types/coach'
import { Badge, Card, Disclosure } from '../../components/ui'
import { CoachText, LegacyText, RuleList, SourceChips, WhyList } from '../../components/CoachText'
import { dateLabel } from '../../lib/format'

export function ProposalIntro({
  proposal,
  statusLabel,
}: {
  proposal: ProposalDetail
  statusLabel: string
}) {
  const next = proposal.next_check
  return (
    <Card className="proposal-intro" data-testid="proposal-intro">
      <div className="proposal-intro-heading">
        <h2>Plan focus</h2>
        <Badge className="status-chip">
          Status: {statusLabel} · Revision {proposal.revision}
        </Badge>
      </div>
      <div className="proposal-headline">
        <CoachText text={proposal.headline} />
      </div>
      <p className="proposal-confidence-line">
        <strong>Confidence:</strong> {proposal.confidence.decision || 'Not stated'}
        {proposal.uncertainty.length > 0 && (
          <>
            {' · '}
            <strong>Unknown:</strong> {proposal.uncertainty.join('; ')}
          </>
        )}
      </p>
      {proposal.why.length > 0 && (
        <section className="proposal-why">
          <h3>Why</h3>
          <WhyList items={proposal.why} />
        </section>
      )}
      <RuleList label="Would change this" rules={proposal.change_triggers} />
      {next && (
        <p className="proposal-next-check">
          <strong>Next check:</strong>{' '}
          {dateLabel(next.on, { weekday: 'short', month: 'short', day: 'numeric' })} — {next.check}
        </p>
      )}
      {proposal.escalation && (
        <p>Suggested next review: {proposal.escalation.replaceAll('_', ' ')}</p>
      )}
      {proposal.coach_note && (
        <Disclosure className="proposal-coach-note">
          <summary>Coach note</summary>
          <CoachText text={proposal.coach_note} />
        </Disclosure>
      )}
      <SourceChips sources={proposal.sources} />
      <Disclosure className="proposal-confidence-details">
        <summary>Confidence details</summary>
        <dl className="proposal-confidence">
          {Object.entries(proposal.confidence).map(([key, value]) => (
            <div key={key}>
              <dt>{key}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      </Disclosure>
      {proposal.revisions.length > 0 && (
        <Disclosure className="proposal-revision-details">
          <summary>Revision history</summary>
          <ol>
            {proposal.revisions.map((entry) => {
              const removed = entry.changed_change_ids.filter(
                (id) => !proposal.changes.some((change) => change.change_id === id),
              )
              return (
                <li key={entry.revision}>
                  <strong>Revision {entry.revision}</strong> ·{' '}
                  {new Date(entry.saved_at).toLocaleString()}
                  <p>{entry.reason}</p>
                  {entry.changed_fields.length > 0 && (
                    <small>
                      Updated fields:{' '}
                      {entry.changed_fields.map((field) => field.replaceAll('_', ' ')).join(', ')}
                      .{' '}
                    </small>
                  )}
                  {entry.changed_change_ids.length > 0 && (
                    <small>
                      Changed sessions: {entry.changed_change_ids.length - removed.length}
                      {removed.length > 0 && `; removed sessions: ${removed.length}`}
                    </small>
                  )}
                </li>
              )
            })}
          </ol>
        </Disclosure>
      )}
      <LegacyText text={proposal.legacy_text} />
    </Card>
  )
}
