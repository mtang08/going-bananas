import { NativeSelect } from '../../components/ui'
import { ApiError } from '../../api/client'
import type { Profile } from '../../api/types/profile'

export function profileBody(profile: Profile) {
  const { version, ...fields } = profile
  return { ...fields, expected_version: version }
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
