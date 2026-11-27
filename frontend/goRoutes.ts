// Only the synthetic development proxy consults this list.
const getRoutes = new Set([
  '/activities',
  '/anchors',
  '/calendar/versions',
  '/calendar/weekly-digest',
  '/calendar/weekly-projection',
  '/coach/proposals',
  '/goals',
  '/google-calendar/events',
  '/google-calendar/status',
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
        /^\/activities\/[^/]+(?:\/workout-history)?$/.test(route) ||
        /^\/coach\/proposals\/[^/]+(?:\/document|\/revisions\/[^/]+)?$/.test(route)
      )
    case 'POST':
      return postRoutes.has(route) || /^\/coach\/proposals\/[^/]+\/(?:revise|decision)$/.test(route)
    case 'PATCH':
      return /^\/(?:goals|trips|google-calendar\/events|v2\/checkins)\/[^/]+$/.test(route)
    case 'PUT':
      return /^\/phone\/checkins\/[^/]+$/.test(route)
    case 'DELETE':
      return /^\/coach\/proposals\/[^/]+$/.test(route)
    default:
      return false
  }
}
