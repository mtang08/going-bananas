import type { ProposalDetail } from '../../api/types/coach'
import { Badge, Card, Disclosure } from '../../components/ui'
import { CoachText } from './ProposalParts'

export function ProposalIntro({
  proposal,
  statusLabel,
  plain,
}: {
  proposal: ProposalDetail
  statusLabel: string
  plain: (text: string) => string
}) {
  return (
    <Card className="proposal-intro">
      <div className="proposal-intro-heading">
        <h2>Plan focus</h2>
        <Badge className="status-chip">
          Status: {statusLabel} · Revision {proposal.revision}
        </Badge>
      </div>
      <CoachText text={plain(proposal.summary)} />
      <div className="proposal-rationale">
        <h3>Why this plan</h3>
        <CoachText text={plain(proposal.rationale)} />
      </div>
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
    </Card>
  )
}
