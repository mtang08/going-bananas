import type { components } from '../generated/planning'
export type IntensityAnchor = components['schemas']['IntensityAnchor']
export type AnchorList = components['schemas']['AnchorList']
export type AnchorCreate = components['schemas']['AnchorInput']
export type AnchorKind = IntensityAnchor['kind']
export type AnchorProtocol = IntensityAnchor['protocol']
export type AnchorConfidence = IntensityAnchor['confidence']
export const ANCHOR_KIND_LABELS: Record<AnchorKind, string> = {
  hr_aerobic_upper: 'Aerobic upper (HR)',
  hr_threshold_lower: 'Threshold lower (HR)',
  speed_aerobic_upper: 'Aerobic upper (pace)',
  speed_threshold_lower: 'Threshold lower (pace)',
  performance_5k: '5K performance',
  performance_1mile: '1 mile performance',
  performance_3min: '3 minute performance',
  performance_20_30min: '20–30 minute performance',
}
export const ANCHOR_UNIT: Record<AnchorKind, 'bpm' | 'mps' | 's' | 'm'> = {
  hr_aerobic_upper: 'bpm',
  hr_threshold_lower: 'bpm',
  speed_aerobic_upper: 'mps',
  speed_threshold_lower: 'mps',
  performance_5k: 's',
  performance_1mile: 's',
  performance_3min: 'm',
  performance_20_30min: 'mps',
}
export const PROTOCOL_LABELS: Record<AnchorProtocol, string> = {
  race_5k: '5K race',
  time_trial_5k: '5K time trial',
  time_trial_1mile: '1 mile time trial',
  time_trial_3min: '3 minute time trial',
  time_trial_20_30min: '20–30 minute time trial',
  workout_derived: 'Workout-derived',
  lab_test: 'Lab test',
  manual: 'Manual entry',
}
