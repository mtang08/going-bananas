export function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day))
  return (
    date.getUTCFullYear() === year && date.getUTCMonth() + 1 === month && date.getUTCDate() === day
  )
}

export function localDate(d = new Date()): string {
  const y = d.getFullYear(),
    m = `${d.getMonth() + 1}`.padStart(2, '0'),
    day = `${d.getDate()}`.padStart(2, '0')
  return `${y}-${m}-${day}`
}
export function addDays(date: string, amount: number): string {
  const d = new Date(`${date}T12:00:00`)
  d.setDate(d.getDate() + amount)
  return localDate(d)
}
export function sportLabel(sport: string): string {
  if (sport === 'running') return 'Run'
  if (sport === 'treadmill_running') return 'Treadmill run'
  if (sport === 'trail_running') return 'Trail run'
  return sport.replaceAll('_', ' ')
}
export function dateLabel(
  date: string,
  options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' },
): string {
  return new Intl.DateTimeFormat('en-US', options).format(new Date(`${date}T12:00:00`))
}
export function distance(m: number | null | undefined, unit: 'mi' | 'km', digits = 1): string {
  return m == null ? '—' : `${(m / (unit === 'mi' ? 1609.344 : 1000)).toFixed(digits)} ${unit}`
}
export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const h = Math.floor(seconds / 3600),
    m = Math.floor((seconds % 3600) / 60)
  return h ? `${h}h ${`${m}`.padStart(2, '0')}m` : `${m}m`
}
export function pace(secondsPerKm: number | null | undefined, unit: 'mi' | 'km'): string {
  if (secondsPerKm == null) return '—'
  const seconds = Math.round(secondsPerKm * (unit === 'mi' ? 1.609344 : 1))
  return `${Math.floor(seconds / 60)}:${`${seconds % 60}`.padStart(2, '0')} /${unit}`
}

export type Unit = 'mi' | 'km'
export const MISSING = 'missing'

export const fmtDistance = (m: number | null | undefined, unit: Unit): string =>
  m == null ? MISSING : distance(m, unit)
export const fmtDuration = (s: number | null | undefined): string =>
  s == null ? MISSING : duration(s)
export function fmtClock(s: number | null | undefined): string {
  if (s == null || !Number.isFinite(s) || s < 0) return MISSING
  const rounded = Math.round(s)
  const seconds = `${rounded % 60}`.padStart(2, '0')
  const minutes = Math.floor(rounded / 60)
  if (rounded < 3600) return `${minutes}:${seconds}`
  return `${Math.floor(rounded / 3600)}:${`${minutes % 60}`.padStart(2, '0')}:${seconds}`
}
export const fmtPaceFromSpeed = (mps: number | null | undefined, unit: Unit): string =>
  mps == null || !Number.isFinite(mps) || mps <= 0 ? MISSING : pace(1000 / mps, unit)
export const fmtPercent = (ratio: number | null | undefined): string =>
  ratio == null ? MISSING : `${Math.round(ratio * 100)}%`
export const fmtRpe = (v: number | null | undefined): string =>
  v == null ? MISSING : `${Number(v.toFixed(1))}/10`
export const statusText = (status: string): string => status.replaceAll('_', ' ')

export function signatureLabel(signature: string | null): string {
  if (!signature) return MISSING
  const body = signature.includes(':') ? signature.slice(signature.indexOf(':') + 1) : signature
  return body
    .split('+')
    .map((part) => {
      const match = /^(\d+)x([td])(\d+)$/.exec(part)
      if (!match) return part
      const [, count, kind, raw] = match
      const value = Number(raw)
      const amount =
        kind === 't'
          ? fmtClock(value)
          : value >= 1000
            ? `${Number((value / 1000).toFixed(2))} km`
            : `${value} m`
      return count === '1' ? amount : `${count} × ${amount}`
    })
    .join(' + ')
}

export function clockToSeconds(text: string): number | null {
  if (!/^\d+:\d{2}(?::\d{2})?$/.test(text)) return null
  const parts = text.split(':').map(Number)
  if (parts.some((part) => !Number.isSafeInteger(part))) return null
  const total =
    parts.length === 2
      ? parts[1] < 60
        ? parts[0] * 60 + parts[1]
        : null
      : parts[1] < 60 && parts[2] < 60
        ? parts[0] * 3600 + parts[1] * 60 + parts[2]
        : null
  return total !== null && Number.isSafeInteger(total) ? total : null
}
export function paceToSpeed(text: string, unit: Unit): number | null {
  const seconds = clockToSeconds(text)
  return seconds == null || seconds <= 0 ? null : (unit === 'mi' ? 1609.344 : 1000) / seconds
}
