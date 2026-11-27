import { saveRoutine } from '../../api/planning'
import { Button, Card, Input } from '../../components/ui'
import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { qk, invalidateKeys } from '../../api/queryKeys'
import {
  WEEKDAY_LABELS,
  type StrengthRoutine,
  type StrengthRoutineSlot,
} from '../../api/types/blocks'
import { ErrorText, Select } from './shared'

export type SlotDraft = Omit<StrengthRoutineSlot, 'id' | 'version'>
const defaults: SlotDraft[] = [0, 4].map((day, i) => ({
  label: `Full body ${i ? 'B' : 'A'}`,
  default_weekday: day,
  lower_body_cost: 'moderate',
  typical_duration_s: 3600,
  main_lower_body_lifts: [],
  active: true,
}))
export const drafts = (routine: StrengthRoutine): SlotDraft[] =>
  routine.slots.length
    ? routine.slots.map((s) => ({
        label: s.label,
        default_weekday: s.default_weekday,
        lower_body_cost: s.lower_body_cost,
        typical_duration_s: s.typical_duration_s,
        main_lower_body_lifts: s.main_lower_body_lifts,
        active: s.active,
      }))
    : defaults
export function ScheduleLink() {
  return (
    <a
      href="#settings"
      onClick={(e) => {
        e.preventDefault()
        const el = document.getElementById('strength-schedule') as HTMLDetailsElement | null
        if (el) {
          el.open = true
          el.scrollIntoView({ behavior: 'smooth' })
        }
      }}
    >
      Edit confirmed strength schedule
    </a>
  )
}
export function StrengthRoutineEditor({
  slots,
  onChange,
}: {
  slots: SlotDraft[]
  onChange: (slots: SlotDraft[]) => void
}) {
  const change = (i: number, value: Partial<SlotDraft>) =>
    onChange(slots.map((slot, n) => (n === i ? { ...slot, ...value } : slot)))
  return (
    <>
      {slots.map((slot, i) => (
        <fieldset key={i}>
          <legend>Slot {i + 1}</legend>
          <label htmlFor={`slot-${i}-label`}>Label</label>
          <Input
            id={`slot-${i}-label`}
            value={slot.label}
            onChange={(e) => change(i, { label: e.target.value })}
          />
          <Select
            id={`slot-${i}-cost`}
            label="Lower-body cost"
            value={slot.lower_body_cost}
            options={{ low: 'Low', moderate: 'Moderate', high: 'High' }}
            onChange={(v) => change(i, { lower_body_cost: v as SlotDraft['lower_body_cost'] })}
          />
          <label htmlFor={`slot-${i}-duration`}>Typical duration (minutes)</label>
          <Input
            id={`slot-${i}-duration`}
            type="number"
            min={5}
            step={5}
            value={slot.typical_duration_s === null ? '' : slot.typical_duration_s / 60}
            onChange={(e) =>
              change(i, {
                typical_duration_s: e.target.value === '' ? null : Number(e.target.value) * 60,
              })
            }
          />
          <label htmlFor={`slot-${i}-lifts`}>Main lower-body lifts</label>
          <Input
            id={`slot-${i}-lifts`}
            value={slot.main_lower_body_lifts.join(', ')}
            onChange={(e) =>
              change(i, { main_lower_body_lifts: e.target.value.split(',').map((v) => v.trim()) })
            }
          />
          <label htmlFor={`slot-${i}-active`}>
            <input
              id={`slot-${i}-active`}
              type="checkbox"
              checked={slot.active}
              onChange={(e) => change(i, { active: e.target.checked })}
            />
            Active
          </label>
          <Button
            variant="link"
            type="button"
            onClick={() => onChange(slots.filter((_, n) => n !== i))}
          >
            Remove slot
          </Button>
        </fieldset>
      ))}
      <Button
        variant="outline"
        type="button"
        onClick={() =>
          onChange([
            ...slots,
            { ...defaults[0], label: '', typical_duration_s: null, main_lower_body_lifts: [] },
          ])
        }
      >
        Add slot
      </Button>
    </>
  )
}
export const cleanSlots = (slots: SlotDraft[]) =>
  slots.map((s) => ({
    ...s,
    label: s.label.trim(),
    main_lower_body_lifts: s.main_lower_body_lifts.map((v) => v.trim()).filter(Boolean),
  }))
export function checkSlots(slots: SlotDraft[]) {
  if (slots.some((s) => !s.label.trim())) throw new Error('Each slot needs a label.')
  if (
    slots.some(
      (s) =>
        s.typical_duration_s !== null &&
        (!Number.isFinite(s.typical_duration_s) ||
          s.typical_duration_s <= 0 ||
          s.typical_duration_s % 300 !== 0),
    )
  )
    throw new Error('Use positive durations in five-minute increments.')
}

export function Routine({ routine, onSaved }: { routine: StrengthRoutine; onSaved: () => void }) {
  const qc = useQueryClient(),
    [slots, setSlots] = useState(() => drafts(routine))
  const save = useMutation({
    mutationFn: () => {
      checkSlots(slots)
      return saveRoutine({
        expected_version: routine.version,
        slots: cleanSlots(slots),
      })
    },
    onSuccess: () => {
      onSaved()
      invalidateKeys(qc, [qk.strengthRoutine])
    },
  })
  const schedule = routine.schedule
  return (
    <Card>
      <h2>Strength routine</h2>
      <p>
        Two full-body sessions a week are the default commitment. The coach plans runs around these.
      </p>
      <p>
        {schedule.strength_schedule_mode === 'alternating'
          ? `Week A: ${schedule.strength_week_a_days.map((d) => WEEKDAY_LABELS[d]).join(', ')}; Week B: ${schedule.strength_week_b_days.map((d) => WEEKDAY_LABELS[d]).join(', ')}`
          : `Confirmed days: ${schedule.scheduled_strength_days.map((d) => WEEKDAY_LABELS[d]).join(', ')}`}
      </p>
      <ScheduleLink />
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <fieldset disabled={save.isPending}>
          <StrengthRoutineEditor slots={slots} onChange={setSlots} />
          <small>Changes apply to future reviews; existing calendar sessions are not moved.</small>
          {slots.filter((s) => s.active).length !== 2 && (
            <p>
              You have {slots.filter((s) => s.active).length} active slots; the default commitment
              is 2.
            </p>
          )}
          <Button type="submit">Save strength routine</Button>
        </fieldset>
      </form>
      <ErrorText error={save.error} />
    </Card>
  )
}
