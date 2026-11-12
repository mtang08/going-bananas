import { dateLabel, type Coverage } from '../api'
import { stateLabel } from './shared'
export function CoverageStrip({ items }: { items: Coverage[] }) {
  if (!items?.length)
    return (
      <div className="notice muted">
        No source coverage has been recorded for this window. A blank day is unreported, not zero
        training.
      </div>
    )
  return (
    <div className="coverage-strip" aria-label="Dataset coverage">
      {items.map((c, index) => (
        <div className="coverage-item" key={`${c.dataset}-${index}`}>
          <span
            className={`coverage-dot ${c.status === 'complete' || c.status === 'success' ? 'good' : 'warn'}`}
          />
          <span>
            <b>{c.dataset.replaceAll('_', ' ')}</b>
            <small>
              {stateLabel(c.status)}
              {c.completed_at ? ` · ${dateLabel(c.completed_at.slice(0, 10))}` : ''}
              {c.reason ? ` · ${c.reason}` : ''}
            </small>
          </span>
        </div>
      ))}
    </div>
  )
}
