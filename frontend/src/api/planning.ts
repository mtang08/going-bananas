import type { components } from './generated/planning'
import { patch, post, put } from './client'

type Schema = components['schemas']

export const saveProfile = (body: Schema['ProfileInput']) =>
  put<Schema['Profile']>('/profile', body)
export const saveInterruption = (body: Schema['RunningInterruptionInput']) =>
  put<Schema['RunningInterruptionView']>('/running-interruption', body)
export const saveRoutine = (body: Schema['RoutineInput']) =>
  put<Schema['StrengthRoutine']>('/strength-routine', body)
export const createAnchor = (body: Schema['AnchorInput']) =>
  post<Schema['IntensityAnchor']>('/anchors', body)
export const createEvent = (body: Schema['EventInput']) =>
  post<Schema['RaceEvent']>('/events', body)
export const updateEvent = (id: string, body: Schema['EventPatch']) =>
  patch<Schema['RaceEvent']>(`/events/${encodeURIComponent(id)}`, body)
export const orderEvents = (body: Schema['EventOrder']) =>
  put<Schema['EventList']>('/events/order', body)
export const linkBenchmark = (id: string, body: Schema['BenchmarkActivityInput']) =>
  put<Schema['BenchmarkActivityResult']>(
    `/blocks/${encodeURIComponent(id)}/benchmark-activity`,
    body,
  )
