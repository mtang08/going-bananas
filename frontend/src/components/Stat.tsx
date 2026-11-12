import { Footprints } from 'lucide-react'
import { Card } from './ui'

export function Stat({
  label,
  value,
  sub,
  icon: Icon,
}: {
  label: string
  value: string
  sub: string
  icon: typeof Footprints
}) {
  return (
    <Card className="min-h-36">
      <div className="flex items-center justify-between gap-3 text-sm font-medium text-muted-foreground">
        <span>{label}</span>
        <Icon size={19} strokeWidth={1.7} className="text-primary" aria-hidden="true" />
      </div>
      <strong className="mt-5 block text-3xl font-semibold tracking-tight">{value}</strong>
      <small className="mt-1 block text-xs text-muted-foreground">{sub}</small>
    </Card>
  )
}
