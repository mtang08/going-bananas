import { useEffect, useState } from 'react'
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
import { PlanningSettings } from './pages/PlanningSettings'

type Authority = Profile['planning_authority']
type Page = 'overview' | 'coach' | 'strength' | 'history' | 'cycle' | 'settings' | 'home' | 'calendar' | 'trends' | 'activity'
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
  { id: 'history', label: 'History', icon: ActivityIcon },
  { id: 'strength', label: 'Strength', icon: HeartPulse },
  { id: 'settings', label: 'Data & settings', icon: Settings2 },
]

export function parseHash(hash: string, authority: Authority): Route {
  const fallback: Route = { page: authority === 'calendar' ? 'home' : 'overview', id: null }
  if (!hash.startsWith('#')) return fallback
  const path = hash.slice(1)
  const allowed = authority === 'calendar'
    ? new Set(['home', 'calendar', 'trends', 'history', 'strength', 'settings', 'coach'])
    : new Set(['overview', 'coach', 'cycle', 'history', 'strength', 'settings'])
  if (allowed.has(path)) return { page: path as Page, id: null }
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
  const [route, setRoute] = useState<Route>({ page: 'overview', id: null })
  const [checkinOpen, setCheckinOpen] = useState(false)
  const [checkinRequest, setCheckinRequest] = useState<CheckinRequest | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [unit, setUnitState] = useState<Unit>(() => localStorage.getItem('gb-unit') === 'km' ? 'km' : 'mi')
  const setUnit = (u: Unit) => { localStorage.setItem('gb-unit', u); setUnitState(u) }
  const ready = useServer<{status:string;database?:boolean}>(['ready'], '/health/ready')
  const profile = useServer<Profile>(['profile'], '/profile')
  const authority = profile.data ? profile.data.data.planning_authority ?? 'legacy' : undefined
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
  const title = page === 'activity' ? 'Activity' : nav.find(item => item.id === page)?.label ?? 'Home'

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
    {!authority && <div className="page-content" role="status">Loading training workspace…</div>}
    {authority === 'legacy' && <>
      {page === 'overview' && <Overview unit={unit} onCheckin={() => openCheckin()}/>}
      {page === 'coach' && <Coach onCheckin={() => openCheckin()} onSetup={() => navigate('settings')}/>}
      {page === 'cycle' && <Cycle onCheckin={() => openCheckin()}/>}
      {page === 'history' && <History unit={unit} onCheckin={() => openCheckin()}/>}
      {page === 'strength' && <Strength/>}
      {page === 'settings' && <Settings unit={unit} setUnit={setUnit} onCheckin={() => openCheckin()}/>}
    </>}
    {authority === 'calendar' && <>
      {page === 'home' && <Home unit={unit} onCheckin={openCheckin}/>}
      {page === 'calendar' && <Calendar unit={unit}/>}
      {page === 'trends' && <Trends unit={unit}/>}
      {page === 'activity' && route.id && <Activity activityId={route.id} unit={unit} onCheckin={openCheckin}/>}
      {page === 'history' && <History unit={unit} onCheckin={() => openCheckin()}/>}
      {page === 'strength' && <Strength/>}
      {page === 'settings' && <PlanningSettings unit={unit} setUnit={setUnit} onCheckin={openCheckin}/>}
      {page === 'coach' && <Coach onCheckin={() => openCheckin()} onSetup={() => navigate('settings')}/>}
    </>}
    <footer className="footer">Local training record · {modeLabel(mode)} · metrics are descriptive</footer>
  </div>{checkinOpen && authority && (authority === 'calendar'
    ? <CheckinModalV2 request={checkinRequest} close={closeCheckin}/>
    : <CheckinModal close={closeCheckin}/>)}</div>
}
