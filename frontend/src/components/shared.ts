import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { api } from '../api'

export type Unit = 'mi' | 'km'

export function useServer<T>(key: unknown[], path: string) { return useQuery({ queryKey: key, queryFn: () => api<T>(path), placeholderData: keepPreviousData }) }

export function stateLabel(status?: string) { return status?.replaceAll('_', ' ') || 'not imported' }
