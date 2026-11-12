import { useState } from 'react'
import { Activity as ActivityIcon, CalendarDays, ChartNoAxesColumn, Footprints, HeartPulse, Menu, Plus, Settings2 } from 'lucide-react'
import { dateLabel, localDate, type Profile } from './api'
import { useServer, type Unit } from './components/shared'
import { Overview } from './pages/Overview'
import { History } from './pages/History'
import { Cycle } from './pages/Cycle'
import { Settings } from './pages/Settings'
import { CheckinModal } from './pages/CheckinModal'
import { Coach } from './pages/Coach'
import { Strength } from './pages/Strength'

type Page = 'overview' | 'coach' | 'strength' | 'history' | 'cycle' | 'settings'

const nav: { id: Page; label: string; icon: typeof ChartNoAxesColumn }[] = [
  { id: 'overview', label: 'Overview', icon: ChartNoAxesColumn },
  { id: 'coach', label: 'Coach', icon: Footprints },
  { id: 'strength', label: 'Strength', icon: HeartPulse },
  { id: 'history', label: 'History', icon: ActivityIcon },
  { id: 'cycle', label: 'Cycle', icon: CalendarDays },
  { id: 'settings', label: 'Data & settings', icon: Settings2 },
]

function modeLabel(mode?: string) { return mode === 'real' ? 'REAL DATA' : mode === 'test' ? 'TEST DATA' : 'DEMO DATA' }

export function App() {
  const [page,setPage]=useState<Page>('overview'),[checkinOpen,setCheckinOpen]=useState(false),[menuOpen,setMenuOpen]=useState(false),[unit,setUnitState]=useState<Unit>(()=>localStorage.getItem('gb-unit')==='km'?'km':'mi')
  const setUnit=(u:Unit)=>{localStorage.setItem('gb-unit',u);setUnitState(u)}
  const ready=useServer<{status:string;database?:boolean}>(['ready'],'/health/ready')
  const profile=useServer<Profile>(['profile'],'/profile')
  const mode=profile.data?.mode||ready.data?.mode
  return <div className="app-shell"><aside className={`sidebar ${menuOpen?'open':''}`}><div className="brand"><div className="brand-mark"><Footprints size={25}/></div><div><strong>going bananas<span className="brand-dot">.</span></strong><small>TRAINING JOURNAL</small></div></div><nav aria-label="Primary navigation">{nav.map(item=>{const Icon=item.icon;return <button key={item.id} className={`nav-item ${page===item.id?'active':''}`} onClick={()=>{setPage(item.id);setMenuOpen(false)}}><Icon size={19} strokeWidth={1.8}/>{item.label}</button>})}</nav><div className="sidebar-bottom"><div className="local-badge"><span className="live-dot"/> Local workspace</div><p>Training, feedback, and research-guided suggestions.</p></div></aside><div className="main-shell"><header className="topbar"><button className="icon-button mobile-menu" aria-label="Open menu" onClick={()=>setMenuOpen(!menuOpen)}><Menu/></button><div className="breadcrumb">TRAINING <span>/</span> {nav.find(x=>x.id===page)?.label.toUpperCase()}</div><div className="top-actions"><span className={`mode-badge ${mode||'demo'}`}>{modeLabel(mode)}</span><span className="top-date">{dateLabel(localDate(),{weekday:'short',month:'short',day:'numeric'})}</span><button className="icon-button help-button" aria-label="Record check-in" onClick={()=>setCheckinOpen(true)}><Plus size={20}/></button></div></header>{ready.data?.data.status==='unavailable' && <div className="notice error global-notice" role="alert">The local database is unavailable. Previously loaded data may be stale.</div>}{page==='overview'&&<Overview unit={unit} onCheckin={()=>setCheckinOpen(true)}/ >}{page==='coach'&&<Coach onCheckin={()=>setCheckinOpen(true)} onSetup={()=>setPage('settings')}/ >}{page==='strength'&&<Strength/>}{page==='history'&&<History unit={unit} onCheckin={()=>setCheckinOpen(true)}/ >}{page==='cycle'&&<Cycle onCheckin={()=>setCheckinOpen(true)}/ >}{page==='settings'&&<Settings unit={unit} setUnit={setUnit} onCheckin={()=>setCheckinOpen(true)}/ >}<footer className="footer">Local training record · {modeLabel(mode)} · metrics are descriptive</footer></div>{checkinOpen&&<CheckinModal close={()=>setCheckinOpen(false)}/>}</div>
}
