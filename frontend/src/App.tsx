import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Activity as ActivityIcon, CalendarDays, ChartNoAxesColumn, Footprints, HeartPulse, Menu, Plus, Settings2 } from 'lucide-react'
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

type Authority = Profile['planning_authority']
type Page = 'overview' | 'coach' | 'strength' | 'history' | 'cycle' | 'settings' | 'home' | 'calendar' | 'trends' | 'activity' | 'block' | 'proposal'
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
]

export function parseHash(hash: string, authority: Authority): Route {
  const fallback: Route = { page: authority === 'calendar' ? 'home' : 'overview', id: null }
  if (!hash.startsWith('#')) return fallback
  const path = hash.slice(1)
  const allowed = authority === 'calendar'
    ? new Set(['home', 'calendar', 'trends', 'block', 'history', 'strength', 'settings', 'coach'])
    : new Set(['overview', 'coach', 'cycle', 'history', 'strength', 'settings'])
  if (allowed.has(path)) return { page: path as Page, id: null }
  if (authority === 'calendar' && /^proposal\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(path)) {
    return { page: 'proposal', id: path.slice('proposal/'.length) }
  }
  if (authority === 'calendar' && path.startsWith('activity/')) {
    try {
      const id = decodeURIComponent(path.slice('activity/'.length))
      if (id && !id.includes('/') && !id.includes('#') && !id.includes('?')) return { page: 'activity', id }
    } catch { return fallback }
  }
  return fallback
}

function modeLabel(mode?: string) { return mode === 'real' ? 'REAL DATA' : mode === 'test' ? 'TEST DATA' : 'DEMO DATA' }

export function App() {
  const queryClient = useQueryClient()
  const [loadedAuthority, setLoadedAuthority] = useState<Authority | undefined>(undefined)
  const [route, setRoute] = useState<Route>({ page: 'overview', id: null })
  const [checkinOpen, setCheckinOpen] = useState(false)
  const [checkinRequest, setCheckinRequest] = useState<CheckinRequest | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [unit, setUnitState] = useState<Unit>(() => localStorage.getItem('gb-unit') === 'km' ? 'km' : 'mi')
  const setUnit = (u: Unit) => { localStorage.setItem('gb-unit', u); setUnitState(u) }
  const ready = useServer<{status:string;database?:boolean}>(['ready'], '/health/ready')
  const profile = useServer<Profile>(['profile'], '/profile')
  const authority = profile.data ? profile.data.data.planning_authority ?? 'legacy' : undefined
  useEffect(() => {
    if (!authority || authority === loadedAuthority) return
    let active = true
    const refresh = async () => {
      if (loadedAuthority) {
        const filter = { predicate: (query: { queryKey: readonly unknown[] }) => !['profile', 'ready'].includes(String(query.queryKey[0])) }
        await queryClient.cancelQueries(filter)
        if (!active) return
        queryClient.removeQueries(filter)
      }
      setCheckinOpen(false)
      setCheckinRequest(null)
      setLoadedAuthority(authority)
    }
    void refresh()
    return () => { active = false }
  }, [authority, loadedAuthority, queryClient])
  const workspaceReady = authority && loadedAuthority === authority
  const mode = profile.data?.mode || ready.data?.mode
  const nav = authority === 'calendar' ? calendarNav : legacyNav
  useEffect(() => {
    if (!authority) return
    const update = () => { setRoute(parseHash(window.location.hash, authority)); setMenuOpen(false) }
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
  const closeCheckin = () => { setCheckinOpen(false); setCheckinRequest(null) }
  const page = route.page
  const title = page === 'activity' ? 'Activity' : page === 'proposal' ? 'Review proposal' : nav.find(item => item.id === page)?.label ?? 'Home'

  return <div className="app-shell"><aside className={`sidebar ${menuOpen ? 'open' : ''}`}>
    <div className="brand"><div className="brand-mark"><Footprints size={25}/></div><div><strong>going bananas<span className="brand-dot">.</span></strong><small>TRAINING JOURNAL</small></div></div>
    <nav aria-label="Primary navigation">{nav.map(item => { const Icon = item.icon; return <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => navigate(item.id)}><Icon size={19} strokeWidth={1.8}/>{item.label}</button> })}</nav>
    <div className="sidebar-bottom"><div className="local-badge"><span className="live-dot"/> Local workspace</div><p>Training, feedback, and research-guided suggestions.</p></div>
  </aside><div className="main-shell"><header className="topbar">
    <button className="icon-button mobile-menu" aria-label="Open menu" onClick={() => setMenuOpen(!menuOpen)}><Menu/></button>
    <div className="breadcrumb">TRAINING <span>/</span> {title.toUpperCase()}</div>
    <div className="top-actions"><span className={`mode-badge ${mode || 'demo'}`}>{modeLabel(mode)}</span><span className="top-date">{dateLabel(localDate(), { weekday: 'short', month: 'short', day: 'numeric' })}</span><button className="icon-button help-button" aria-label="Record check-in" onClick={() => openCheckin()}><Plus size={20}/></button></div>
  </header>
    {ready.data?.data.status === 'unavailable' && <div className="notice error global-notice" role="alert">The local database is unavailable. Previously loaded data may be stale.</div>}
    {!workspaceReady && <div className="page-content" role="status">Loading training workspace…</div>}
    {workspaceReady && authority === 'legacy' && <>
      {page === 'overview' && <Overview unit={unit} onCheckin={() => openCheckin()}/>}
      {page === 'coach' && <Coach onCheckin={() => openCheckin()} onSetup={() => navigate('settings')}/>}
      {page === 'cycle' && <Cycle onCheckin={() => openCheckin()}/>}
      {page === 'history' && <History unit={unit} onCheckin={() => openCheckin()}/>}
      {page === 'strength' && <Strength/>}
      {page === 'settings' && <Settings unit={unit} setUnit={setUnit} onCheckin={() => openCheckin()}/>}
    </>}
    {workspaceReady && authority === 'calendar' && <>
      {page === 'home' && <Home unit={unit} onCheckin={openCheckin}/>}
      {page === 'calendar' && <Calendar unit={unit}/>}
      {page === 'trends' && <Trends unit={unit}/>}
      {page === 'block' && <Block/>}
      {page === 'proposal' && route.id && <ProposalReview proposalId={route.id}/>}
      {page === 'activity' && route.id && <Activity activityId={route.id} unit={unit} onCheckin={openCheckin}/>}
      {page === 'history' && <History unit={unit} onCheckin={() => openCheckin()}/>}
      {page === 'strength' && <Strength/>}
      {page === 'settings' && <PlanningSettings unit={unit} setUnit={setUnit} onCheckin={openCheckin}/>}
      {page === 'coach' && <Coach readOnly onCheckin={() => openCheckin()} onSetup={() => navigate('settings')}/>}
    </>}
    <footer className="footer">Local training record · {modeLabel(mode)} · metrics are descriptive</footer>
  </div>{checkinOpen && workspaceReady && authority && (authority === 'calendar'
    ? <CheckinModalV2 request={checkinRequest} close={closeCheckin}/>
    : <CheckinModal close={closeCheckin}/>)}</div>
}
