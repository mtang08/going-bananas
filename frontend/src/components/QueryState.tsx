import { Button, Card } from './ui'

export function QueryState({
  loading,
  error,
  stale,
  children,
  retry,
}: {
  loading: boolean
  error?: Error | null
  stale?: boolean
  children: React.ReactNode
  retry?: () => void
}) {
  if (loading)
    return (
      <Card className="m-6 flex items-center gap-3 text-sm text-muted-foreground" role="status">
        <span
          className="size-4 animate-spin rounded-full border-2 border-primary/20 border-t-primary"
          aria-hidden="true"
        />{' '}
        Loading local data…
      </Card>
    )
  if (error && !stale)
    return (
      <Card className="m-6 border-destructive/30" role="alert">
        <strong>Could not load this view</strong>
        <p className="my-3 text-sm text-muted-foreground">{error.message}</p>
        {retry && (
          <Button type="button" variant="outline" onClick={retry}>
            Try again
          </Button>
        )}
      </Card>
    )
  return (
    <>
      {error && stale && (
        <div
          className="mx-6 my-4 rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
          role="status"
        >
          Showing the last loaded data. Refresh failed: {error.message}
        </div>
      )}
      {children}
    </>
  )
}
