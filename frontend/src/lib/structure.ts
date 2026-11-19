import { fmtClock, fmtPaceFromSpeed, type Unit } from './format'
import type { ExpandedStep, PlannedStep, StructureItem } from '../api/types/calendar'

export function flattenStructure(items: StructureItem[]): ExpandedStep[] {
  const validNumber = (value: unknown, positive: boolean): value is number =>
    typeof value === 'number' && Number.isFinite(value) && (positive ? value > 0 : value >= 0)
  const validateStep = (value: unknown): value is PlannedStep => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false
    const step = value as Record<string, unknown>
    if (
      Object.keys(step).some(
        (key) => !['type', 'duration_type', 'duration_value', 'target'].includes(key),
      )
    )
      return false
    if (
      !['warmup', 'work', 'recovery', 'cooldown'].includes(String(step.type)) ||
      !['time', 'distance'].includes(String(step.duration_type)) ||
      !validNumber(step.duration_value, true)
    )
      return false
    if (step.target == null) return true
    if (typeof step.target !== 'object' || Array.isArray(step.target)) return false
    const target = step.target as Record<string, unknown>
    if (Object.keys(target).some((key) => !['modality', 'low', 'high', 'effort_cue'].includes(key)))
      return false
    if (target.modality === 'effort')
      return (
        target.low == null &&
        target.high == null &&
        typeof target.effort_cue === 'string' &&
        Boolean(target.effort_cue.trim())
      )
    if (target.modality !== 'speed' && target.modality !== 'hr') return false
    if (
      !validNumber(target.low, target.modality === 'hr') ||
      !validNumber(target.high, target.modality === 'hr') ||
      target.low > target.high
    )
      return false
    return (
      target.effort_cue == null ||
      (typeof target.effort_cue === 'string' && Boolean(target.effort_cue.trim()))
    )
  }
  if (!Array.isArray(items) || items.length === 0) throw new Error('invalid_structure')
  const expanded: ExpandedStep[] = []
  const append = (step: PlannedStep, step_path: string, repeat_index: number | null) => {
    if (!validateStep(step) || expanded.length >= 100) throw new Error('invalid_structure')
    expanded.push({ ...step, step_path, repeat_index, expanded_step: expanded.length + 1 })
  }
  items.forEach((item, i) => {
    if (!item || typeof item !== 'object' || Array.isArray(item))
      throw new Error('invalid_structure')
    if (item.type !== 'repeat') {
      append(item, `${i}`, null)
      return
    }
    if (
      Object.keys(item).some((key) => !['type', 'count', 'steps'].includes(key)) ||
      !Number.isInteger(item.count) ||
      item.count < 2 ||
      !Array.isArray(item.steps) ||
      item.steps.length === 0 ||
      item.steps.some((child) => !validateStep(child))
    )
      throw new Error('invalid_structure')
    for (let j = 0; j < item.count; j++)
      item.steps.forEach((child, k) => append(child, `${i}.steps.${k}`, j))
  })
  return expanded
}
export function formatStep(step: PlannedStep, unit: Unit): string {
  const labels = { warmup: 'Warm-up', work: 'Work', recovery: 'Recovery', cooldown: 'Cool-down' }
  const amount =
    step.duration_type === 'distance'
      ? `${Math.round(step.duration_value)} m`
      : fmtClock(step.duration_value)
  const target = step.target
  let cue = 'effort'
  if (
    target?.modality === 'speed' &&
    target.low != null &&
    target.high != null &&
    target.low > 0 &&
    target.high > 0
  ) {
    cue = `${fmtPaceFromSpeed(target.high, unit)}–${fmtPaceFromSpeed(target.low, unit)}`
  } else if (target?.modality === 'hr' && target.low != null && target.high != null) {
    cue = `${target.low}–${target.high} bpm`
  } else if (target?.modality === 'effort' && target.effort_cue?.trim()) {
    cue = target.effort_cue.trim()
  }
  return `${labels[step.type]} ${amount} · ${cue}`
}
