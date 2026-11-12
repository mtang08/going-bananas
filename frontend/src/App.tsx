import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import {
  Activity as ActivityIcon,
  BookOpen,
  CalendarDays,
  ChartNoAxesColumn,
  Footprints,
  HeartPulse,
  Menu,
  Plus,
  Settings2,
} from 'lucide-react'
import { dateLabel, localDate, type CheckinRequest, type Profile } from './api'
import { useServer, type Unit } from './components/shared'
import { Overview } from './pages/Overview'
import { History } from './pages/History'
import { Cycle } from './pages/Cycle'
import { Settings } from './pages/Settings'
import { CheckinModal } from './pages/CheckinModal'
import { CheckinModalV2 } from './pages/CheckinModalV2'
import { Coach } from './pages/Coach'
import { Strength } from './pages/Strength'
import { Home } from './pages/Home'
import { Calendar } from './pages/Calendar'
import { Trends } from './pages/Trends'
import { Activity } from './pages/Activity'
import { Block } from './pages/Block'
import { ProposalReview } from './pages/ProposalReview'
import { PlanningSettings } from './pages/PlanningSettings'
import { Guide } from './pages/Guide'
import { Badge, Button, Dialog, DialogContent, DialogTitle, DialogTrigger } from './components/ui'

type Authority = Profile['planning_authority']
type Page =
  | 'overview'
  | 'coach'
  | 'strength'
  | 'history'
  | 'cycle'
  | 'settings'
  | 'home'
  | 'calendar'
  | 'trends'
  | 'activity'
  | 'block'
  | 'proposal'
  | 'guide'
type Route = { page: Page; id: string | null }
type NavItem = { id: Page; label: string; icon: typeof ChartNoAxesColumn }

const legacyNav: NavItem[] = [
  { id: 'overview', label: 'Overview', icon: ChartNoAxesColumn },
  { id: 'coach', label: 'Coach', icon: Footprints },
  { id: 'strength', label: 'Strength', icon: HeartPulse },
  { id: 'history', label: 'History', icon: ActivityIcon },
  { id: 'cycle', label: 'Cycle', icon: CalendarDays },
  { id: 'settings', label: 'Data & settings', icon: Settings2 },
]
const calendarNav: NavItem[] = [
  { id: 'home', label: 'Home', icon: Footprints },
  { id: 'calendar', label: 'Calendar', icon: CalendarDays },
  { id: 'trends', label: 'Trends', icon: ChartNoAxesColumn },
  { id: 'block', label: 'Training block', icon: CalendarDays },
  { id: 'history', label: 'History', icon: ActivityIcon },
  { id: 'strength', label: 'Strength', icon: HeartPulse },
  { id: 'coach', label: 'Coaching history', icon: Footprints },
  { id: 'settings', label: 'Data & settings', icon: Settings2 },
  { id: 'guide', label: 'User guide', icon: BookOpen },
]

export function parseHash(hash: string, authority: Authority): Route {
  const fallback: Route = { page: authority === 'calendar' ? 'home' : 'overview', id: null }
  if (!hash.startsWith('#')) return fallback
  const path = hash.slice(1)
  const allowed =
    authority === 'calendar'
      ? new Set([
          'home',
          'calendar',
          'trends',
          'block',
          'history',
          'strength',
          'settings',
          'coach',
          'guide',
        ])
      : new Set(['overview', 'coach', 'cycle', 'history', 'strength', 'settings'])
  if (allowed.has(path)) return { page: path as Page, id: null }
  if (
    authority === 'calendar' &&
    /^proposal\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(path)
  ) {
    return { page: 'proposal', id: path.slice('proposal/'.length) }
  }
  if (authority === 'calendar' && path.startsWith('activity/')) {
    try {
      const id = decodeURIComponent(path.slice('activity/'.length))
      if (id && !id.includes('/') && !id.includes('#') && !id.includes('?'))
        return { page: 'activity', id }
    } catch {
      return fallback
    }
  }
  return fallback
}

function modeLabel(mode?: string) {
  return mode === 'real' ? 'REAL DATA' : mode === 'test' ? 'TEST DATA' : 'DEMO DATA'
}

export function App() {
  const queryClient = useQueryClient()
  const [loadedAuthority, setLoadedAuthority] = useState<Authority | undefined>(undefined)
  const [route, setRoute] = useState<Route>({ page: 'overview', id: null })
  const [checkinOpen, setCheckinOpen] = useState(false)
  const [checkinRequest, setCheckinRequest] = useState<CheckinRequest | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [unit, setUnitState] = useState<Unit>(() =>
    localStorage.getItem('gb-unit') === 'km' ? 'km' : 'mi',
  )
  const setUnit = (u: Unit) => {
    localStorage.setItem('gb-unit', u)
    setUnitState(u)
  }
  const ready = useServer<{ status: string; database?: boolean }>(['ready'], '/health/ready')
  const profile = useServer<Profile>(['profile'], '/profile')
  const authority = profile.data ? (profile.data.data.planning_authority ?? 'legacy') : undefined
  useEffect(() => {
    if (!authority || authority === loadedAuthority) return
    let active = true
    const refresh = async () => {
      if (loadedAuthority) {
        const filter = {
          predicate: (query: { queryKey: readonly unknown[] }) =>
            !['profile', 'ready'].includes(String(query.queryKey[0])),
        }
        await queryClient.cancelQueries(filter)
        if (!active) return
        queryClient.removeQueries(filter)
      }
      setCheckinOpen(false)
      setCheckinRequest(null)
      setLoadedAuthority(authority)
    }
    void refresh()
    return () => {
      active = false
    }
  }, [authority, loadedAuthority, queryClient])
  const workspaceReady = authority && loadedAuthority === authority
  const mode = profile.data?.mode || ready.data?.mode
  const nav = authority === 'calendar' ? calendarNav : legacyNav
  useEffect(() => {
    if (!authority) return
    const update = () => {
      setRoute(parseHash(window.location.hash, authority))
      setMenuOpen(false)
    }
    update()
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [authority])
  const navigate = (page: Page) => {
    window.location.hash = page
    setRoute({ page, id: null })
    setMenuOpen(false)
  }
  const openCheckin = (request?: CheckinRequest) => {
    setCheckinRequest(request ?? { kind: 'exception', activityId: null, prompt: null })
    setCheckinOpen(true)
  }
  const closeCheckin = () => {
    setCheckinOpen(false)
    setCheckinRequest(null)
  }
  const page = route.page
  const title =
    page === 'activity'
      ? 'Activity'
      : page === 'proposal'
        ? 'Review proposal'
        : (nav.find((item) => item.id === page)?.label ?? 'Home')

  const navigation = (
    <nav aria-label="Primary navigation" className="grid gap-1">
      {nav.map((item) => {
        const Icon = item.icon
        return (
          <Button
            type="button"
            variant={page === item.id ? 'secondary' : 'ghost'}
            key={item.id}
            aria-current={page === item.id ? 'page' : undefined}
            className="h-10 w-full justify-start gap-3 px-3 text-sm"
            onClick={() => navigate(item.id)}
          >
            <Icon size={18} strokeWidth={1.8} />
            {item.label}
          </Button>
        )
      })}
    </nav>
  )
  const brand = (
    <div className="flex items-center gap-3 px-3 pb-7">
      <div className="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <Footprints size={23} />
      </div>
      <div>
        <strong className="text-base font-semibold tracking-tight">going bananas.</strong>
        <small className="mt-0.5 block text-[10px] font-medium tracking-widest text-muted-foreground">
          TRAINING JOURNAL
        </small>
      </div>
    </div>
  )

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-card px-3 py-6 lg:flex">
        {brand}
        {navigation}
        <div className="mt-auto border-t px-3 pt-5">
          <div className="flex items-center gap-2 text-xs font-medium">
            <span className="size-2 rounded-full bg-primary" /> Local workspace
          </div>
          <p className="mb-0 mt-3 text-xs text-muted-foreground">
            Training, feedback, and research-guided suggestions.
          </p>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex min-h-16 items-center justify-between gap-3 border-b bg-card px-4 py-3 sm:px-6 lg:px-10">
          <Dialog open={menuOpen} onOpenChange={setMenuOpen}>
            <DialogTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="lg:hidden"
                aria-label="Open menu"
              >
                <Menu />
              </Button>
            </DialogTrigger>
            <DialogContent
              className="left-0 top-0 h-dvh w-72 max-w-[calc(100%-2rem)] translate-x-0 translate-y-0 rounded-none border-y-0 border-l-0 p-4 pt-8 sm:max-w-72"
              aria-describedby={undefined}
            >
              <DialogTitle className="sr-only">Navigation</DialogTitle>
              {brand}
              {navigation}
            </DialogContent>
          </Dialog>
          <div className="min-w-0 flex-1 truncate text-sm font-medium">
            <span className="hidden text-muted-foreground sm:inline">
              Training <span className="mx-2 text-border">/</span>
            </span>
            {title}
          </div>
          <div className="flex items-center gap-3">
            <Badge
              variant={mode === 'real' ? 'secondary' : 'outline'}
              className="text-[10px] tracking-wide"
            >
              {modeLabel(mode)}
            </Badge>
            <span className="hidden text-xs text-muted-foreground md:inline">
              {dateLabel(localDate(), { weekday: 'short', month: 'short', day: 'numeric' })}
            </span>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label="Record check-in"
              onClick={() => openCheckin()}
            >
              <Plus size={20} />
            </Button>
          </div>
        </header>
        {ready.data?.data.status === 'unavailable' && (
          <div className="notice error global-notice" role="alert">
            The local database is unavailable. Previously loaded data may be stale.
          </div>
        )}
        {!workspaceReady && (
          <div className="page-content" role="status">
            Loading training workspace…
          </div>
        )}
        {workspaceReady && authority === 'legacy' && (
          <>
            {page === 'overview' && <Overview unit={unit} onCheckin={() => openCheckin()} />}
            {page === 'coach' && (
              <Coach onCheckin={() => openCheckin()} onSetup={() => navigate('settings')} />
            )}
            {page === 'cycle' && <Cycle onCheckin={() => openCheckin()} />}
            {page === 'history' && <History unit={unit} onCheckin={() => openCheckin()} />}
            {page === 'strength' && <Strength />}
            {page === 'settings' && (
              <Settings unit={unit} setUnit={setUnit} onCheckin={() => openCheckin()} />
            )}
          </>
        )}
        {workspaceReady && authority === 'calendar' && (
          <>
            {page === 'home' && <Home unit={unit} onCheckin={openCheckin} />}
            {page === 'calendar' && <Calendar unit={unit} />}
            {page === 'trends' && <Trends unit={unit} />}
            {page === 'block' && <Block />}
            {page === 'guide' && <Guide />}
            {page === 'proposal' && route.id && <ProposalReview proposalId={route.id} />}
            {page === 'activity' && route.id && (
              <Activity activityId={route.id} unit={unit} onCheckin={openCheckin} />
            )}
            {page === 'history' && <History unit={unit} onCheckin={() => openCheckin()} />}
            {page === 'strength' && <Strength />}
            {page === 'settings' && (
              <PlanningSettings unit={unit} setUnit={setUnit} onCheckin={openCheckin} />
            )}
            {page === 'coach' && (
              <Coach
                readOnly
                onCheckin={() => openCheckin()}
                onSetup={() => navigate('settings')}
              />
            )}
          </>
        )}
        <footer className="border-t px-6 py-5 text-center text-xs text-muted-foreground">
          Local training record · {modeLabel(mode)} · metrics are descriptive
        </footer>
      </div>
      {checkinOpen &&
        workspaceReady &&
        authority &&
        (authority === 'calendar' ? (
          <CheckinModalV2 request={checkinRequest} close={closeCheckin} />
        ) : (
          <CheckinModal close={closeCheckin} />
        ))}
    </div>
  )
}
