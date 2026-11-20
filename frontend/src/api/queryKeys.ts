import type { QueryClient } from '@tanstack/react-query'

export function invalidateKeys(qc: QueryClient, keys: readonly (readonly unknown[])[]): void {
  for (const key of keys) void qc.invalidateQueries({ queryKey: [...key] })
}

export const qk = {
  calendar: ['v2', 'calendar'] as const,
  calendarView: (version: number | 'head') => ['v2', 'calendar', 'view', version] as const,
  calendarWeek: (start: string | 'current', version: number | 'head') =>
    ['v2', 'calendar', 'week', start, version] as const,
  calendarVersions: ['v2', 'calendar', 'versions'] as const,
  calendarDiff: (from: number, to: number) => ['v2', 'calendar', 'diff', from, to] as const,
  weeklyDigest: (weekStart: string | 'current') =>
    ['v2', 'calendar', 'weekly-digest', weekStart] as const,
  prompts: ['v2', 'prompts'] as const,
  metrics: ['v2', 'metrics'] as const,
  metricsWindows: ['v2', 'metrics', 'windows'] as const,
  metricsRecovery: (start: string, end: string) =>
    ['v2', 'metrics', 'recovery', start, end] as const,
  activityExecution: (id: string) => ['v2', 'metrics', 'execution', id] as const,
  workoutProgression: (groupBy: string) =>
    ['v2', 'metrics', 'workout-progression', groupBy] as const,
  workoutHistory: (id: string) => ['v2', 'metrics', 'workout-history', id] as const,
  activity: (id: string) => ['v2', 'activity', id] as const,
  activitiesNear: (start: string, end: string) => ['v2', 'activities', start, end, null] as const,
  exceptions: ['v2', 'exceptions'] as const,
  goals: ['v2', 'goals'] as const,
  events: ['v2', 'events'] as const,
  anchors: ['v2', 'anchors'] as const,
  strengthRoutine: ['v2', 'strength-routine'] as const,
  blocksActive: ['v2', 'blocks', 'active'] as const,
  blockBenchmarks: ['v2', 'blocks', 'benchmarks'] as const,
  profile: ['profile'] as const,
  weeklyProjection: ['v2', 'calendar', 'weekly-projection'] as const,
  activityDetails: ['v2', 'activity'] as const,
  activities: ['v2', 'activities'] as const,
  activityRuns: (start: string, end: string) => ['v2', 'activities', start, end, 'runs'] as const,
  activityLatest: (day: string) => ['v2', 'activities', 'latest', day] as const,
  proposals: ['v2', 'proposals'] as const,
  proposalsOpen: ['v2', 'proposals', 'open'] as const,
  proposal: (id: string) => ['v2', 'proposals', id] as const,
  blocks: ['v2', 'blocks'] as const,
  blockHistory: (uid: string | undefined) => ['v2', 'blocks', 'history', uid] as const,
  eventBlocks: (id: string) => ['v2', 'blocks', 'events', id] as const,
  ready: ['ready'] as const,
  sync: ['sync'] as const,
  syncJob: (id: string) => ['sync', 'job', id] as const,
  syncPending: ['sync', 'pending'] as const,
  syncOutcome: ['sync', 'outcome'] as const,
}

// Everything a sync can change. Settings data (goals, events, anchors, routine, profile) is excluded.
export const refreshAfterSync = [
  qk.calendar,
  qk.metrics,
  qk.activityDetails,
  qk.activities,
  qk.prompts,
  qk.exceptions,
  qk.blocks,
  qk.proposals,
] as const
