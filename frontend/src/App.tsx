import { qk } from './api/queryKeys'
import { useEffect, useState } from 'react'
import {
  BookOpen,
  CalendarDays,
  ChartNoAxesColumn,
  Footprints,
  Menu,
  Moon,
  Plus,
  Settings2,
  Sun,
} from 'lucide-react'
import { dateLabel, localDate, validDate } from './lib/format'
import type { CheckinRequest } from './api/types/checkins'
import type { Profile } from './api/types/profile'
import { useServer } from './components/shared'
import type { Unit } from './lib/format'
import { CheckinModalV2 } from './pages/CheckinModalV2'
import { Home } from './pages/Home'
import { Calendar } from './pages/Calendar'
import { Trends } from './pages/Trends'
import { Activity } from './pages/Activity'
import { Block } from './pages/Block'
import { ProposalReview } from './pages/ProposalReview'
import { PlanningSettings } from './pages/PlanningSettings'
import { Guide } from './pages/Guide'
import { Badge, Button, Dialog, DialogContent, DialogTitle, DialogTrigger } from './components/ui'

type Page =
  'home' | 'calendar' | 'trends' | 'block' | 'settings' | 'activity' | 'proposal' | 'guide'
type Route = { page: Page; id: string | null }
type NavItem = { id: Page; label: string; icon: typeof ChartNoAxesColumn }

const nav: NavItem[] = [
  { id: 'home', label: 'Home', icon: Footprints },
  { id: 'calendar', label: 'Calendar', icon: CalendarDays },
  { id: 'trends', label: 'Trends', icon: ChartNoAxesColumn },
  { id: 'block', label: 'Training block', icon: CalendarDays },
  { id: 'settings', label: 'Settings', icon: Settings2 },
]

export function parseHash(hash: string): Route {
  const fallback: Route = { page: 'home', id: null }
  if (!hash.startsWith('#')) return fallback
  const path = hash.slice(1)
  const allowed = new Set(['home', 'calendar', 'trends', 'block', 'settings', 'guide'])
  if (allowed.has(path)) return { page: path as Page, id: null }
  if (/^proposal\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(path)) {
    return { page: 'proposal', id: path.slice('proposal/'.length) }
  }
  if (path.startsWith('calendar/')) {
    const date = path.slice('calendar/'.length)
    return validDate(date) ? { page: 'calendar', id: date } : fallback
  }
  if (path.startsWith('activity/')) {
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
  const [route, setRoute] = useState<Route>({ page: 'home', id: null })
  const [checkinOpen, setCheckinOpen] = useState(false)
  const [checkinRequest, setCheckinRequest] = useState<CheckinRequest | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [darkMode, setDarkMode] = useState(() => document.documentElement.dataset.theme !== 'light')
  const toggleTheme = () => {
    const theme = darkMode ? 'light' : 'dark'
    document.documentElement.dataset.theme = theme
    localStorage.setItem('going-bananas-theme', theme)
    setDarkMode(!darkMode)
  }
  const [unit, setUnitState] = useState<Unit>(() =>
    localStorage.getItem('gb-unit') === 'km' ? 'km' : 'mi',
  )
  const setUnit = (u: Unit) => {
    localStorage.setItem('gb-unit', u)
    setUnitState(u)
  }
  const ready = useServer<{ status: string; database?: boolean }>(qk.ready, '/health/ready')
  const profile = useServer<Profile>(qk.profile, '/profile')
  const mode = profile.data?.mode || ready.data?.mode
  useEffect(() => {
    const update = () => {
      setRoute(parseHash(window.location.hash))
      setMenuOpen(false)
    }
    update()
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
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
        : page === 'guide'
          ? 'User guide'
          : (nav.find((item) => item.id === page)?.label ?? 'Home')
  const dbDown = ready.isError || ready.data?.data.status === 'unavailable'

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
        <span aria-hidden="true" className="text-2xl">
          🦍
        </span>
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
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r bg-card px-3 py-6 jungle-sidebar lg:flex">
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
          <div className="flex items-center gap-2 sm:gap-3">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Dark mode"
              aria-pressed={darkMode}
              onClick={toggleTheme}
            >
              {darkMode ? (
                <Sun aria-hidden="true" size={17} />
              ) : (
                <Moon aria-hidden="true" size={17} />
              )}
            </Button>
            <Badge
              variant={mode === 'real' ? 'secondary' : 'outline'}
              className="text-[10px] tracking-wide"
            >
              {modeLabel(mode)}
            </Badge>
            <Button variant="ghost" size="sm" asChild>
              <a href="#guide">
                <BookOpen size={16} /> Guide
              </a>
            </Button>
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
        {dbDown ? (
          <div className="notice error global-notice" role="alert">
            Database unavailable — start it with make db-start
          </div>
        ) : (
          profile.error && (
            <div className="notice error global-notice" role="alert">
              Could not load the training workspace: {profile.error.message}{' '}
              <Button variant="outline" size="sm" onClick={() => void profile.refetch()}>
                Retry
              </Button>
            </div>
          )
        )}
        {!profile.data && !profile.error && (
          <div className="page-content" role="status">
            Loading training workspace…
          </div>
        )}
        {profile.data && (
          <>
            {page === 'home' && <Home unit={unit} onCheckin={openCheckin} />}
            {page === 'calendar' && <Calendar unit={unit} weekStart={route.id} />}
            {page === 'trends' && <Trends unit={unit} />}
            {page === 'block' && <Block unit={unit} />}
            {page === 'guide' && <Guide />}
            {page === 'proposal' && route.id && (
              <ProposalReview proposalId={route.id} unit={unit} />
            )}
            {page === 'activity' && route.id && (
              <Activity activityId={route.id} unit={unit} onCheckin={openCheckin} />
            )}
            {page === 'settings' && <PlanningSettings unit={unit} setUnit={setUnit} />}
          </>
        )}
        <footer className="border-t px-6 py-5 text-center text-xs text-muted-foreground">
          Local training record · {modeLabel(mode)} · metrics are descriptive
        </footer>
      </div>
      {checkinOpen && profile.data && (
        <CheckinModalV2 request={checkinRequest} close={closeCheckin} />
      )}
    </div>
  )
}
