

export function QueryState({ loading, error, stale, children, retry }: { loading: boolean; error?: Error | null; stale?: boolean; children: React.ReactNode; retry?: () => void }) {
  if (loading) return <div className="state-card" role="status"><span className="spinner"/> Loading local data…</div>
  if (error && !stale) return <div className="state-card error" role="alert"><strong>Could not load this view</strong><p>{error.message}</p>{retry && <button className="button" onClick={retry}>Try again</button>}</div>
  return <>{error && stale && <div className="notice warning" role="status">Showing the last loaded data. Refresh failed: {error.message}</div>}{children}</>
}
