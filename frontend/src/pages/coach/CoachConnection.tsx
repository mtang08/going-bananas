import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowUpRight } from 'lucide-react'
import { api, post, type Envelope } from '../../api/client'
import { invalidateKeys, qk } from '../../api/queryKeys'
import type { CoachAuth, CoachChat } from '../../api/types/coachChat'
import { Button, Card } from '../../components/ui'

const authPath = '/coach/chat/auth'

function authorizationLink(value: string | null | undefined) {
  if (!value) return null
  try {
    const url = new URL(value)
    if (
      url.origin === 'https://auth.openai.com' &&
      url.pathname === '/oauth/authorize' &&
      !url.username &&
      !url.password &&
      !url.hash
    )
      return url.href
  } catch {
    // The authorization button stays unavailable for an unreadable URL.
  }
  return null
}

export function CoachConnection({
  chatError,
  hasCoachReply,
}: {
  chatError: CoachChat['error']
  hasCoachReply: boolean
}) {
  const qc = useQueryClient()
  const auth = useQuery({
    queryKey: qk.coachAuth,
    queryFn: ({ signal }) => api<CoachAuth>(authPath, { signal }),
    refetchInterval: (query) => (query.state.data?.data.status === 'waiting' ? 1000 : false),
    refetchIntervalInBackground: true,
    staleTime: 0,
    retry: false,
  })
  const readStopped = () => qc.cancelQueries({ queryKey: qk.coachAuth })
  const sync = (response: Envelope<CoachAuth>) => qc.setQueryData(qk.coachAuth, response)
  const recover = () => invalidateKeys(qc, [qk.coachAuth])
  const start = useMutation({
    mutationFn: () => post<CoachAuth>(`${authPath}/start`, {}),
    networkMode: 'always',
    onMutate: readStopped,
    onSuccess: sync,
    onError: recover,
  })
  const cancel = useMutation({
    mutationFn: () => post<CoachAuth>(`${authPath}/cancel`, {}),
    networkMode: 'always',
    onMutate: readStopped,
    onSuccess: sync,
    onError: recover,
  })
  const state = auth.data?.data
  const status = state?.status
  const waiting = status === 'waiting'
  const needsLogin = chatError?.code === 'auth_required' || status === 'signed_out'
  const signedIn = status === 'signed_in'
  const pending = start.isPending || cancel.isPending
  const blockingError = start.error?.message ?? cancel.error?.message ?? state?.error?.message
  const checkingAccount = status === undefined && auth.isPending
  if (signedIn && !needsLogin) return null
  if (hasCoachReply && !needsLogin && !waiting && !pending) return null
  if (checkingAccount && !needsLogin) return null

  const link = authorizationLink(state?.url)
  const description =
    blockingError ??
    (signedIn
      ? 'You’re signed in. You can send your last message again.'
      : waiting
        ? link
          ? 'Finish signing in in your browser, then return to this conversation.'
          : 'Preparing the browser sign-in link…'
        : status === 'cancelled'
          ? 'Sign-in was cancelled. You can try again when you’re ready.'
          : needsLogin
            ? 'Connect your ChatGPT account to continue with the coach. Your conversation is saved.'
            : 'Connect your ChatGPT account if this is your first time using the coach.')
  return (
    <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
      <div>
        <h2 className="m-0 text-sm font-semibold">Coach connection</h2>
        <p
          className="m-0 mt-1 text-sm text-muted-foreground"
          role={blockingError ? 'alert' : 'status'}
        >
          {description}
        </p>
        {auth.error && (
          <Button
            type="button"
            variant="link"
            size="sm"
            className="px-0"
            onClick={() => void auth.refetch()}
          >
            Refresh sign-in status
          </Button>
        )}
      </div>
      {!signedIn && (
        <div className="flex flex-wrap gap-2">
          {waiting ? (
            <>
              {link && (
                <Button asChild size="sm">
                  <a href={link} target="_blank" rel="noopener noreferrer">
                    Open ChatGPT sign-in <ArrowUpRight size={16} aria-hidden="true" />
                  </a>
                </Button>
              )}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={pending}
                onClick={() => {
                  start.reset()
                  cancel.mutate()
                }}
              >
                {cancel.isPending ? 'Cancelling…' : 'Cancel sign-in'}
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant={needsLogin ? 'default' : 'outline'}
              size="sm"
              disabled={pending}
              onClick={() => {
                cancel.reset()
                start.mutate()
              }}
            >
              {start.isPending ? 'Starting sign-in…' : 'Sign in with ChatGPT'}
            </Button>
          )}
        </div>
      )}
    </Card>
  )
}
