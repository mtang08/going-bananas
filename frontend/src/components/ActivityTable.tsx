import { Button, Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui'
import { dateLabel, distance, duration, pace, type Activity } from '../api'
import type { Unit } from './shared'
export function ActivityTable({
  items,
  unit,
  compact = false,
  onSelect,
}: {
  items: Activity[]
  unit: Unit
  compact?: boolean
  onSelect?: (a: Activity) => void
}) {
  return (
    <div className="table-scroll">
      <Table className="activity-table">
        <TableHeader>
          <TableRow>
            <TableHead>Date</TableHead>
            <TableHead>Activity</TableHead>
            <TableHead>Distance</TableHead>
            <TableHead>Time</TableHead>
            {!compact && <TableHead>Moving pace</TableHead>}
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.map((a) => (
            <TableRow
              key={a.id}
              onClick={() => onSelect?.(a)}
              className={onSelect ? 'selectable' : ''}
            >
              <TableCell>
                {onSelect ? (
                  <Button
                    onClick={() => onSelect(a)}
                    variant="link"
                    className="table-link h-auto p-0"
                  >
                    {dateLabel(a.local_date)}
                  </Button>
                ) : (
                  dateLabel(a.local_date)
                )}
              </TableCell>
              <TableCell>
                <span className="activity-name">{a.sport.replaceAll('_', ' ')}</span>
                <small>
                  {a.classification?.label_source === 'heuristic'
                    ? `Auto: ${a.classification.effective_label}`
                    : a.classification?.label_source === 'manual'
                      ? `Manual ${a.classification.effective_label}`
                      : a.classification?.label_source === 'source'
                        ? `Source ${a.classification.effective_label}`
                        : a.workout_label || a.subtype || 'Run type unknown'}
                </small>
              </TableCell>
              <TableCell>{distance(a.distance_m, unit)}</TableCell>
              <TableCell>{duration(a.elapsed_s)}</TableCell>
              {!compact && <TableCell>{pace(a.moving_pace_s_per_km, unit)}</TableCell>}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
