import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '../api'

export type Unit = 'mi' | 'km'

export function useServer<T>(key: unknown[], path: string) { return useQuery({ queryKey: key, queryFn: () => api<T>(path), placeholderData: keepPreviousData }) }

export function stateLabel(status?: string) { return status?.replaceAll('_', ' ') || 'not imported' }

export function relativeTime(iso: string, now: Date = new Date()): string {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return 'unknown'
  const minutes = Math.floor((now.getTime() - then) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} h ago`
  const days = Math.floor(hours / 24)
  return days === 1 ? '1 day ago' : `${days} days ago`
}
