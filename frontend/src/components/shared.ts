import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api, type Coverage } from '../api'

export type Unit = 'mi' | 'km'

export function useServer<T>(key: unknown[], path: string) { return useQuery({ queryKey: key, queryFn: () => api<T>(path), placeholderData: keepPreviousData }) }

export function stateLabel(status?: string) { return status?.replaceAll('_', ' ') || 'not imported' }

export function isPartial(coverage: Coverage[]) { return coverage.some(c => c.status !== 'complete' && c.status !== 'complete_window' && c.status !== 'success') }
