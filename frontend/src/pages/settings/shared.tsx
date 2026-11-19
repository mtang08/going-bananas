import { NativeSelect } from '../../components/ui'
import { ApiError, type Profile } from '../../api'

export function profileBody(profile: Profile) {
  const keys = [
    'timezone',
    'cycle_anchor',
    'anchor_confirmed',
    'strength_days_confirmed',
    'scheduled_strength_days',
    'strength_schedule_mode',
    'strength_week_a_start',
    'strength_week_a_days',
    'strength_week_b_days',
    'mobility_week_a_days',
    'mobility_week_b_days',
    'mobility_optional_days',
    'facts',
    'preferences',
    'unknowns',
  ] as const
  return {
    ...Object.fromEntries(keys.map((key) => [key, profile[key]])),
    expected_version: profile.version,
  }
}
export function ErrorText({ error }: { error: Error | null }) {
  if (!error) return null
  const message =
    error instanceof ApiError && error.code === 'version_conflict'
      ? 'Settings changed in another tab. Reload and try again.'
      : error instanceof ApiError && error.code === 'calendar_exists'
        ? 'A calendar already exists. Edit it on the Calendar page.'
        : error.message
  return (
    <p className="error-text" role="alert">
      {message}
    </p>
  )
}
export function Select({
  id,
  label,
  value,
  options,
  onChange,
}: {
  id: string
  label: string
  value: string
  options: Record<string, string>
  onChange: (value: string) => void
}) {
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <NativeSelect id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {Object.entries(options).map(([v, text]) => (
          <option key={v} value={v}>
            {text}
          </option>
        ))}
      </NativeSelect>
    </>
  )
}
