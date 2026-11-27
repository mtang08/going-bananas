// Only the synthetic development proxy consults this list.
const getRoutes = new Set([
  '/activities',
  '/anchors',
  '/blocks/active',
  '/blocks/benchmarks',
  '/calendar',
  '/calendar/week',
  '/calendar/diff',
  '/calendar/versions',
  '/calendar/weekly-digest',
  '/calendar/weekly-projection',
  '/coach/chat',
  '/coach/chat/auth',
  '/coach/proposals',
  '/events',
  '/goals',
  '/google-calendar/events',
  '/google-calendar/status',
  '/exceptions',
  '/settings/login-startup',
  '/metrics/long-runs',
  '/metrics/workout-progression',
  '/prompts',
  '/strength-routine',
  '/metrics/recovery',
  '/running-interruption',
  '/trips',
  '/v2/checkins',
])
const postRoutes = new Set([
  '/anchors',
  '/calendar/bootstrap',
  '/calendar/edits',
  '/calendar/rollback',
  '/coach/chat/messages',
  '/coach/chat/cancel',
  '/coach/chat/new',
  '/coach/chat/auth/start',
  '/coach/chat/auth/cancel',
  '/events',
  '/goals',
  '/google-calendar/sync',
  '/trips',
  '/v2/checkins',
])

export function servedByGo(method: string | undefined, path: string): boolean {
  const base = '/api/v1'
  if (!path.startsWith(base + '/')) return false
  const route = path.slice(base.length)
  switch (method) {
    case 'GET':
      return (
        getRoutes.has(route) ||
        /^\/blocks\/[^/]+\/history$/.test(route) || /^\/events\/[^/]+\/blocks$/.test(route) ||
        /^\/activities\/[^/]+(?:\/(?:workout-history|execution))?$/.test(route) ||
        /^\/coach\/proposals\/[^/]+(?:\/document|\/revisions\/[^/]+)?$/.test(route)
      )
    case 'POST':
      return postRoutes.has(route) || /^\/prompts\/[^/]+\/dismiss$/.test(route) || /^\/exceptions\/[^/]+\/dismiss$/.test(route) || /^\/exception-patches\/[^/]+\/resolve$/.test(route) || /^\/coach\/proposals\/[^/]+\/(?:revise|decision)$/.test(route)
    case 'PATCH':
      return /^\/(?:events|goals|trips|google-calendar\/events|v2\/checkins)\/[^/]+$/.test(route)
    case 'PUT':
      return route === '/strength-routine' || /^\/(?:activities|strength\/history)\/[^/]+\/rpe$/.test(route) || route === '/settings/login-startup' || /^\/blocks\/[^/]+\/benchmark-activity$/.test(route) || /^\/calendar\/completions\/[^/]+$/.test(route) || route === '/events/order' || /^\/phone\/checkins\/[^/]+$/.test(route)
    case 'DELETE':
      return /^\/coach\/proposals\/[^/]+$/.test(route)
    default:
      return false
  }
}
