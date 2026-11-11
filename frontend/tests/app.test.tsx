import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App } from '../src/App'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({children}:{children:React.ReactNode}) => <div>{children}</div>,
  BarChart: ({children}:{children:React.ReactNode}) => <div>{children}</div>,
  LineChart: ({children}:{children:React.ReactNode}) => <div>{children}</div>,
  Bar: () => null, Line: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
}))

let responseMode:'demo'|'real'='demo'
let importItems:unknown[]=[]
const wrap = (data: unknown) => ({schema_version:'v1',data_revision:3,mode:responseMode,data})
const profile = {version:1,timezone:'America/New_York',cycle_anchor:'2026-11-02',anchor_confirmed:true,strength_days_confirmed:true,scheduled_strength_days:[0,4],strength_schedule_mode:'weekly',strength_week_a_start:null,strength_week_a_days:[],strength_week_b_days:[],mobility_week_a_days:[],mobility_week_b_days:[],mobility_optional_days:[],facts:{},preferences:{},unknowns:[]}
const summary = {as_of:'2026-11-15',timezone:'America/New_York',metric_version:'analytics.v1',window:{start_date:'2026-10-19',end_date:'2026-11-15'},current_week:{distance_m:11265.408,run_count:2,missing_distance_count:0},rolling_7:{distance_m:11265.408,run_count:2,missing_distance_count:0},rolling_14:{distance_m:16093.44,run_count:4,missing_distance_count:0},selected:{distance_m:16093.44,run_count:4,missing_distance_count:0,longest_elapsed_s:700,strength_count:2,strength_duration_s:3600,strength_unknown_duration_count:1,low_impact_count:0,low_impact_duration_s:0,workout_distribution:{easy:1,quality:0,long:1,other:0,unknown:2}},weekly:[{start_date:'2026-11-09',end_date:'2026-11-15',distance_m:11265.408,run_count:2,missing_distance_count:0,strength_count:1}],recent_runs:[],coverage:[{dataset:'activities',status:'partial',reason:'import in progress'}]}
const recovery = {timezone:'America/New_York',series:{sleep:[],hrv:[],resting_hr:[]},trailing_7:{sleep:{mean:null,n:0,days:7},hrv:{mean:null,n:0,days:7},resting_hr:{mean:null,n:0,days:7}},coverage:[]}

let requests: {url:string;method:string;body:unknown;headers:Headers}[] = []
let profileRecord={...profile}
let activityItems:unknown[]=[]
beforeEach(() => {
  requests=[]
  profileRecord={...profile}
  activityItems=[]
  responseMode='demo'
  importItems=[]
  localStorage.clear()
  vi.stubGlobal('fetch',vi.fn(async (input:string, init?:RequestInit) => {
    const url=String(input),method=init?.method||'GET'
    requests.push({url,method,body:init?.body?JSON.parse(String(init.body)):null,headers:new Headers(init?.headers)})
    if(url.includes('/profile')&&method==='PUT')profileRecord={...profileRecord,...JSON.parse(String(init?.body)),version:profileRecord.version+1}
    const data = url.includes('/sync/jobs/') ? {id:'job-1',dataset:'activities',status:'succeeded'} : url.includes('/sync') && method==='POST' ? {jobs:[{id:'job-1',dataset:'activities',status:'queued'}]} : url.includes('/sync/status') ? {datasets:[],active_jobs:[]} : url.includes('/weekly-summary') ? {week_start:'2026-11-09',week_end:'2026-11-15',summary:summary.selected,checkins:[],questions:[],coverage:[]} : url.includes('/summary') ? (url.includes('as_of=2020-12-31') ? {...summary,window:{start_date:'2020-01-02',end_date:'2020-12-31'}} : summary) : url.includes('/recovery') ? recovery : url.includes('/profile') ? profileRecord : url.includes('/health/ready') ? {status:'ok',database:true} : url.includes('/checkins') && method==='POST' ? {id:'checkin-1'} : url.includes('/activities/') ? activityItems[0] : url.includes('/activities') ? {items:activityItems,next_cursor:null,timezone:'America/New_York',coverage:[]} : url.includes('/imports') ? {items:importItems} : {items:[]}
    return {ok:true,status:200,json:async()=>wrap(data)} as Response
  }))
})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});return render(<QueryClientProvider client={client}><App/></QueryClientProvider>)}

describe('analytics dashboard',()=>{
  it('uses summary values and discloses partial coverage and demo mode',async()=>{
    mount()
    await waitFor(()=>expect(screen.getAllByText('7.0 mi').length).toBeGreaterThan(0))
    expect(screen.getAllByText('10.0 mi').length).toBeGreaterThan(0)
    expect(screen.getAllByText('DEMO DATA').length).toBeGreaterThan(0)
    expect(screen.getByText(/Some source windows are incomplete/)).toBeInTheDocument()
    expect(requests.filter(x=>x.url.includes('/summary'))).toHaveLength(1)
  })
  it('one-tap check-in sends explicit values with local mutation header and stable key',async()=>{
    mount()
    fireEvent.click(screen.getAllByRole('button',{name:'Record check-in'})[0])
    fireEvent.click(screen.getByRole('button',{name:/No issues; usual energy/}))
    await waitFor(()=>expect(requests.some(x=>x.method==='POST')).toBe(true))
    const sent=requests.find(x=>x.method==='POST')!
    expect(sent.url).toContain('/checkins')
    expect(sent.body).toMatchObject({symptoms:'none',gait:'normal',feeling:'usual'})
    expect(sent.headers.get('X-Local-Request')).toBe('1')
    expect((sent.body as {idempotency_key:string}).idempotency_key).toBeTruthy()
  })
  it('keeps existing profile values when saving only the display timezone',async()=>{
    mount()
    fireEvent.click(screen.getByRole('button',{name:'Data & settings'}))
    const tz=await screen.findByLabelText('Display timezone')
    fireEvent.change(tz,{target:{value:'America/Chicago'}})
    fireEvent.click(screen.getByRole('button',{name:'Save profile'}))
    await waitFor(()=>expect(requests.some(x=>x.method==='PUT')).toBe(true))
    expect(requests.find(x=>x.method==='PUT')!.body).toMatchObject({timezone:'America/Chicago',cycle_anchor:'2026-11-02',anchor_confirmed:true,strength_days_confirmed:true,scheduled_strength_days:[0,4]})
  })
  it('saves a confirmed Week A/B pattern once and reloads strength and mobility days',async()=>{
    mount()
    fireEvent.click(screen.getByRole('button',{name:'Data & settings'}))
    fireEvent.change(await screen.findByLabelText('Strength schedule'),{target:{value:'alternating'}})
    fireEvent.change(screen.getByLabelText('Week A Monday'),{target:{value:'2026-11-09'}})
    const weeks=document.querySelectorAll('.schedule-week')
    const check=(week:Element,label:string,day:string)=>{
      const heading=within(week as HTMLElement).getByText(label)
      const picker=heading.parentElement!
      fireEvent.click(within(picker).getByLabelText(day))
    }
    check(weeks[0],'Full-body strength · two days','Mon')
    check(weeks[0],'Full-body strength · two days','Fri')
    check(weeks[0],'Required gym mobility','Wed')
    check(weeks[1],'Full-body strength · two days','Tue')
    check(weeks[1],'Full-body strength · two days','Sat')
    check(weeks[1],'Required gym mobility','Thu')
    const optional=screen.getByText('Optional mobility · both weeks').parentElement!
    fireEvent.click(within(optional).getByLabelText('Sun'))
    fireEvent.click(screen.getByLabelText('I confirm this repeating strength and mobility pattern'))
    fireEvent.click(screen.getByRole('button',{name:'Save profile'}))
    await waitFor(()=>expect(requests.some(x=>x.method==='PUT')).toBe(true))
    expect(requests.find(x=>x.method==='PUT')!.body).toMatchObject({strength_schedule_mode:'alternating',strength_week_a_start:'2026-11-09',strength_week_a_days:[0,4],strength_week_b_days:[1,5],mobility_week_a_days:[2],mobility_week_b_days:[3],mobility_optional_days:[6],strength_days_confirmed:true})
    fireEvent.click(screen.getByRole('button',{name:'Overview'}))
    fireEvent.click(screen.getByRole('button',{name:'Data & settings'}))
    expect(await screen.findByLabelText('Strength schedule')).toHaveValue('alternating')
    expect(screen.getByLabelText('Week A Monday')).toHaveValue('2026-11-09')
    expect(within(document.querySelectorAll('.schedule-week')[1].querySelectorAll('.field')[0] as HTMLElement).getByLabelText('Sat')).toBeChecked()
  })
  it('allows a real-mode manual sync with the local mutation header',async()=>{
    responseMode='real'
    mount()
    fireEvent.click(screen.getByRole('button',{name:'Data & settings'}))
    fireEvent.click(await screen.findByRole('button',{name:'Sync now'}))
    await waitFor(()=>expect(requests.some(x=>x.url.endsWith('/sync')&&x.method==='POST')).toBe(true))
    const sent=requests.find(x=>x.url.endsWith('/sync')&&x.method==='POST')!
    expect(sent.body).toEqual({})
    expect(sent.headers.get('X-Local-Request')).toBe('1')
  })
  it('loads an archived history window and rejects windows beyond the API limit',async()=>{
    mount()
    fireEvent.click(screen.getByRole('button',{name:'History'}))
    fireEvent.change(screen.getByLabelText('Start date'),{target:{value:'2019-12-31'}})
    fireEvent.change(screen.getByLabelText('End date'),{target:{value:'2020-12-31'}})
    expect(screen.getByText('Choose a window of 366 dates or fewer.')).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Start date'),{target:{value:'2020-01-01'}})
    fireEvent.change(screen.getByLabelText('End date'),{target:{value:'2020-12-30'}})
    fireEvent.click(screen.getByRole('button',{name:'Show dates'}))
    await waitFor(()=>expect(requests.some(x=>x.url.includes('/activities?')&&x.url.includes('start_date=2020-01-01')&&x.url.includes('end_date=2020-12-30'))).toBe(true))
    fireEvent.click(screen.getByRole('button',{name:'Previous date window'}))
    await waitFor(()=>expect(requests.filter(x=>x.url.includes('/activities?')).map(x=>x.url)).toContainEqual(expect.stringContaining('end_date=2019-12-31')))
  })
  it('uses the selected overview year for summary and recovery',async()=>{
    mount()
    fireEvent.click(screen.getByRole('button',{name:'1 year'}))
    fireEvent.change(screen.getByLabelText('Through date'),{target:{value:'2020-12-31'}})
    await waitFor(()=>expect(requests.some(x=>x.url.includes('/summary?')&&x.url.includes('days=365')&&x.url.includes('as_of=2020-12-31'))).toBe(true))
    await waitFor(()=>expect(requests.some(x=>x.url.includes('/recovery?')&&x.url.includes('end_date=2020-12-31')&&x.url.includes('start_date=2020-01-02'))).toBe(true))
  })
  it('shows provisional run classification with reasons and leaves manual correction available',async()=>{
    activityItems=[{id:'run-1',start_at:'2026-11-10T12:00:00Z',local_date:'2026-11-10',sport:'running',distance_m:10000,elapsed_s:3600,moving_s:3500,moving_pace_s_per_km:350,workout_label:'long',classification:{method:'historical_relative_v1',suggested_label:'long',effective_label:'long',label_source:'heuristic',confidence:'low',reasons:['Longer than recent recorded runs.'],metrics:{prior_runs:3}},annotations:{version:0,workout_label:null}}]
    mount()
    fireEvent.click(screen.getByRole('button',{name:'History'}))
    expect(await screen.findByText('Auto: long')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Auto: long').closest('tr')!.querySelector('button')!)
    fireEvent.click(await screen.findByText('Auto: long · details'))
    expect(screen.getByText('Longer than recent recorded runs.')).toBeInTheDocument()
    expect(screen.getByLabelText('Workout label')).toHaveValue('long')
  })
  it('shows only approved import counts and dates',async()=>{
    importItems=[{id:'secret-id',source_kind:'garmin_export',status:'partial',started_at:'2020-01-01T00:00:00Z',finished_at:'2020-01-02T00:00:00Z',counters:{activities:{seen:12,new_revisions:11,changed:1,rejected:1},datasets:{activities:{first_date:'2019-01-01',last_date:'2020-12-31',fully_enumerated:false,raw_path:'/private/secret.zip'}},archive_sha256:'secret-hash',preserved_only:{unsupported:2,'private@example.com':1}},filename:'secret.zip'}]
    mount()
    fireEvent.click(screen.getByRole('button',{name:'Data & settings'}))
    expect(await screen.findByText('Garmin export')).toBeInTheDocument()
    expect(screen.getByText(/Seen 12 · New revisions 11/)).toBeInTheDocument()
    expect(screen.getByText(/Jan 1, 2019 – Dec 31, 2020/)).toBeInTheDocument()
    expect(screen.getByText(/Observed dates only; completeness unverified/)).toBeInTheDocument()
    expect(screen.getByText(/3 recovery entries were preserved/)).toBeInTheDocument()
    expect(screen.getByText(/Import incomplete/)).toBeInTheDocument()
    expect(screen.queryByText(/secret-id|secret.zip|secret-hash|private@example.com|\/private/)).not.toBeInTheDocument()
  })
})
