import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, put } from '../../api/client'
import { qk } from '../../api/queryKeys'
import type { LoginStartup as LoginStartupState } from '../../api/types/loginStartup'
import { Badge, Button, Card } from '../../components/ui'

const path = '/settings/login-startup'

export function LoginStartup() {
  const qc = useQueryClient()
  const status = useQuery({
    queryKey: qk.loginStartup,
    queryFn: ({ signal }) => api<LoginStartupState>(path, { signal }),
    retry: false,
    staleTime: 0,
  })
  const save = useMutation({
    mutationFn: (enabled: boolean) => put<LoginStartupState>(path, { enabled }),
    networkMode: 'always',
    onMutate: () => qc.cancelQueries({ queryKey: qk.loginStartup }),
    onSuccess: (result) => qc.setQueryData(qk.loginStartup, result),
    onError: () => qc.invalidateQueries({ queryKey: qk.loginStartup }),
  })
  const current = status.data?.data
  const enabled = current?.enabled
  const canSet = current?.status === 'enabled' || current?.status === 'disabled'
  const checking = status.fetchStatus === 'fetching' && (status.isPending || status.isError)
  const unavailable = status.isError || status.fetchStatus === 'paused'
  const error = save.error?.message ?? status.error?.message
  const retry =
    unavailable || current?.status === 'unavailable' || current?.status === 'other_checkout'
  const pending = save.isPending
  const updateMessage = pending
    ? save.variables
      ? 'Turning on startup…'
      : 'Turning off startup…'
    : checking
      ? 'Checking startup status…'
      : current?.message

  return (
    <Card role="region" aria-labelledby="login-startup-title">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 basis-60">
          <h2 id="login-startup-title" className="m-0 text-base font-semibold">
            Start Going Bananas when I log in
          </h2>
          <p id="login-startup-description" className="mb-0 mt-1 text-sm text-muted-foreground">
            Start the local app in the background when you sign in to this Mac. Turning this off
            keeps the current dashboard and worker running.
          </p>
        </div>
        {canSet && typeof enabled === 'boolean' && !unavailable ? (
          <Button
            type="button"
            variant={enabled ? 'secondary' : 'outline'}
            size="sm"
            className="min-w-20"
            role="switch"
            aria-labelledby="login-startup-title"
            aria-describedby="login-startup-description"
            aria-checked={enabled}
            aria-disabled={pending}
            onClick={() => {
              if (!pending) save.mutate(!enabled)
            }}
          >
            {enabled ? 'On' : 'Off'}
          </Button>
        ) : (
          !checking && (
            <Badge variant="outline">
              {unavailable || current?.status !== 'unsupported'
                ? 'Unavailable'
                : 'Unavailable here'}
            </Badge>
          )
        )}
      </div>
      {updateMessage && (
        <p className="mb-0 mt-3 text-sm text-muted-foreground" role="status">
          {updateMessage}
        </p>
      )}
      {error && (
        <p className="error-text mb-0 mt-3" role="alert">
          {error}
        </p>
      )}
      {retry && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-3"
          disabled={status.isFetching || pending}
          onClick={() => {
            save.reset()
            void status.refetch()
          }}
        >
          Refresh startup status
        </Button>
      )}
    </Card>
  )
}
