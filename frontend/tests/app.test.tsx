import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { App, parseHash } from '../src/App'

vi.mock('recharts', () => ({
  ResponsiveContainer: ({children}:{children:React.ReactNode}) => <div>{children}</div>,
  BarChart: ({children}:{children:React.ReactNode}) => <div>{children}</div>,
  LineChart: ({children}:{children:React.ReactNode}) => <div>{children}</div>,
  Bar: () => null, Line: () => null, CartesianGrid: () => null, XAxis: () => null, YAxis: () => null, Tooltip: () => null,
}))

let responseMode:'demo'|'real'='demo'
let importItems:unknown[]=[]
const wrap = (data: unknown) => ({schema_version:'v1',data_revision:3,mode:responseMode,data})
const profile = {planning_authority:'legacy' as 'legacy'|'calendar',version:1,timezone:'America/New_York',cycle_anchor:'2026-11-02',anchor_confirmed:true,strength_days_confirmed:true,scheduled_strength_days:[0,4],strength_schedule_mode:'weekly',strength_week_a_start:null,strength_week_a_days:[],strength_week_b_days:[],mobility_week_a_days:[],mobility_week_b_days:[],mobility_optional_days:[],facts:{},preferences:{},unknowns:[]}
const calendarView = {today:'2026-11-15',timezone:'America/New_York',start:'2026-11-08',end:'2026-11-28',version:1,head:1,undo:null,last_planned_date:'2026-11-28',sessions:[],completions:[]}
const execution = {activity:{id:'run-1',start_at:'2026-11-14T12:00:00Z',end_at:'2026-11-14T12:30:00Z',local_date:'2026-11-14',sport:'running',distance_m:5000,timer_s:1800,elapsed_s:1800,fit_status:'not_fetched'},planned:null,completion:null,laps:[],watch_steps:[],planned_actual:null,intervals:null,intensity:null,rpe:{effective:null,source:null,manual:null,garmin_fit:null,srpe_load_au:null},symptoms:[]}
const summary = {as_of:'2026-11-15',timezone:'America/New_York',metric_version:'analytics.v1',window:{start_date:'2026-10-19',end_date:'2026-11-15'},current_week:{distance_m:11265.408,run_count:2,missing_distance_count:0},rolling_7:{distance_m:11265.408,run_count:2,missing_distance_count:0},rolling_14:{distance_m:16093.44,run_count:4,missing_distance_count:0},selected:{distance_m:16093.44,run_count:4,missing_distance_count:0,longest_elapsed_s:700,strength_count:2,strength_duration_s:3600,strength_unknown_duration_count:1,low_impact_count:0,low_impact_duration_s:0,workout_distribution:{easy:1,quality:0,long:1,other:0,unknown:2}},weekly:[{start_date:'2026-11-09',end_date:'2026-11-15',distance_m:11265.408,run_count:2,missing_distance_count:0,strength_count:1}],recent_runs:[],coverage:[{dataset:'activities',status:'partial',reason:'import in progress'}]}
const recovery = {timezone:'America/New_York',series:{sleep:[],hrv:[],resting_hr:[]},trailing_7:{sleep:{mean:null,n:0,days:7},hrv:{mean:null,n:0,days:7},resting_hr:{mean:null,n:0,days:7}},coverage:[]}

const proposalId = '11111111-1111-4111-8111-111111111111'
const emptyProposal = {id:proposalId,operation:'review_rolling_plan',status:'pending',summary:'Keep this plan',rationale:'Continue',confidence:{decision:'moderate',evidence:'moderate',data:'moderate'},head:1,is_current:true,changes:[],anchor_changes:[],block_change:null,evidence_ids:[],policy_ids:[],recipe_ids:[],validation_errors:[]}
let requests: {url:string;method:string;body:unknown;headers:Headers}[] = []
let profileRecord={...profile}
let activityItems:unknown[]=[]
beforeEach(() => {
  requests=[]
  profileRecord={...profile}
  activityItems=[]
  responseMode='demo'
  importItems=[]
  window.location.hash=''
  localStorage.clear()
  vi.stubGlobal('fetch',vi.fn(async (input:string, init?:RequestInit) => {
    const url=String(input),method=init?.method||'GET'
    requests.push({url,method,body:init?.body?JSON.parse(String(init.body)):null,headers:new Headers(init?.headers)})
    if(url.includes('/profile')&&method==='PUT')profileRecord={...profileRecord,...JSON.parse(String(init?.body)),version:profileRecord.version+1}
    const data = url.includes(`/coach/proposals/${proposalId}`) ? emptyProposal : url.includes('/calendar/versions') ? {items:[]} : url.endsWith('/calendar') ? calendarView : url.includes('/prompts') ? {items:[]} : url.includes('/blocks/active') ? null : url.includes('/strength-routine') ? {version:0,slots:[],schedule:profileRecord} : url.includes('/coach/v2/daily') ? null : url.includes('/execution') ? execution : url.includes('/sync/jobs/') ? {id:'job-1',dataset:'activities',status:'succeeded'} : url.includes('/sync') && method==='POST' ? {jobs:[{id:'job-1',dataset:'activities',status:'queued'}]} : url.includes('/sync/status') ? {datasets:[],active_jobs:[]} : url.includes('/weekly-summary') ? {week_start:'2026-11-09',week_end:'2026-11-15',summary:summary.selected,checkins:[],questions:[],coverage:[]} : url.includes('/summary') ? (url.includes('as_of=2020-12-31') ? {...summary,window:{start_date:'2020-01-02',end_date:'2020-12-31'}} : summary) : url.includes('/recovery') ? recovery : url.includes('/profile') ? profileRecord : url.includes('/health/ready') ? {status:'ok',database:true} : url.includes('/checkins') && method==='POST' ? {id:'checkin-1'} : url.includes('/activities/') ? activityItems[0] : url.includes('/activities') ? {items:activityItems,next_cursor:null,timezone:'America/New_York',coverage:[]} : url.includes('/imports') ? {items:importItems} : {items:[]}
    return {ok:true,status:200,json:async()=>wrap(data)} as Response
  }))
})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function mount(client=new QueryClient({defaultOptions:{queries:{retry:false}}})){return render(<QueryClientProvider client={client}><App/></QueryClientProvider>)}

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
    await screen.findByRole('heading',{name:'Your training, in context.'})
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
    await screen.findByRole('heading',{name:'Your training, in context.'})
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
    await screen.findByRole('heading',{name:'Your training, in context.'})
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

describe('authority shell',()=>{
  it('parses only routes permitted by the resolved authority',()=>{
    expect(parseHash('#calendar','legacy')).toEqual({page:'overview',id:null})
    expect(parseHash('#coach','legacy')).toEqual({page:'coach',id:null})
    expect(parseHash('#cycle','calendar')).toEqual({page:'home',id:null})
    expect(parseHash('#activity/run%20one','calendar')).toEqual({page:'activity',id:'run one'})
    expect(parseHash('#activity/%ZZ','calendar')).toEqual({page:'home',id:null})
    expect(parseHash('#activity/%2F','calendar')).toEqual({page:'home',id:null})
    expect(parseHash('#block','calendar')).toEqual({page:'block',id:null})
    expect(parseHash(`#proposal/${proposalId}`,'calendar')).toEqual({page:'proposal',id:proposalId})
    for (const hash of ['#proposal/%ZZ','#proposal/no-id',`#proposal/${proposalId}/extra`]) expect(parseHash(hash,'calendar')).toEqual({page:'home',id:null})
    expect(parseHash(`#proposal/${proposalId}`,'legacy')).toEqual({page:'overview',id:null})
  })
  it('keeps the legacy Coach and Cycle navigation and modal',async()=>{
    mount()
    fireEvent.click(await screen.findByRole('button',{name:'Coach'}))
    expect(await screen.findByRole('heading',{name:'Plan, train, review.'})).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'Cycle'}))
    expect(await screen.findByRole('heading',{name:'Keep the rhythm visible.'})).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button',{name:'Record check-in'})[0])
    expect(screen.getByRole('button',{name:/No issues; usual energy/})).toBeInTheDocument()
  })
  it('opens calendar Home, follows navigation hashes, and uses the v2 check-in',async()=>{
    profileRecord={...profile,planning_authority:'calendar'}
    mount()
    expect(await screen.findByTestId('today-card')).toBeInTheDocument()
    expect(screen.getAllByTestId('strip-day')).toHaveLength(14)
    expect(screen.queryByRole('button',{name:'Cycle'})).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button',{name:'Calendar'}))
    expect(window.location.hash).toBe('#calendar')
    expect(await screen.findByRole('heading',{name:'Calendar.'})).toBeInTheDocument()
    window.location.hash='#unknown'
    fireEvent(window,new Event('hashchange'))
    expect(await screen.findByTestId('today-card')).toBeInTheDocument()
    fireEvent.click(screen.getAllByRole('button',{name:'Record check-in'})[0])
    expect(screen.getByRole('dialog',{name:'Record check-in'})).toBeInTheDocument()
    expect(screen.getByRole('heading',{name:'Something to report?'})).toBeInTheDocument()
  })
  it('routes an activity deep link and keeps existing settings controls',async()=>{
    profileRecord={...profile,planning_authority:'calendar'}
    window.location.hash='#activity/run-1'
    mount()
    expect(await screen.findByRole('heading',{name:/Run ·/})).toBeInTheDocument()
    expect(requests.some(x=>x.url.includes('/activities/run-1/execution'))).toBe(true)
    fireEvent.click(screen.getByRole('button',{name:'Data & settings'}))
    expect(await screen.findByRole('heading',{name:'Planning settings'})).toBeInTheDocument()
    expect(await screen.findByLabelText('Display timezone')).toBeInTheDocument()
    expect(screen.getAllByRole('heading',{name:'Planning settings'})).toHaveLength(1)
  })
  it('opens a saved proposal without applying it and navigates to the block',async()=>{
    profileRecord={...profile,planning_authority:'calendar'}
    window.location.hash=`#proposal/${proposalId}`
    mount()
    expect(await screen.findByRole('heading',{name:'Keep this plan'})).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'Accept (no changes)'})).toBeInTheDocument()
    expect(requests.some(request=>request.method==='POST')).toBe(false)
    fireEvent.click(screen.getByRole('button',{name:'Training block'}))
    expect(await screen.findByRole('heading',{name:'No active training block'})).toBeInTheDocument()
    expect(window.location.hash).toBe('#block')
  })
  it('discards old planning caches and closes the old check-in when authority changes',async()=>{
    const client=new QueryClient({defaultOptions:{queries:{retry:false,staleTime:Infinity}}})
    mount(client)
    await screen.findByRole('heading',{name:'Your training, in context.'})
    fireEvent.click(screen.getAllByRole('button',{name:'Record check-in'})[0])
    client.setQueryData(['v2','sentinel'],{old:true})
    client.setQueryData(['legacy','sentinel'],{old:true})
    await act(async()=>{client.setQueryData(['profile'],wrap({...profile,planning_authority:'calendar'}))})
    expect(await screen.findByTestId('today-card')).toBeInTheDocument()
    expect(client.getQueryData(['v2','sentinel'])).toBeUndefined()
    expect(client.getQueryData(['legacy','sentinel'])).toBeUndefined()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(requests.some(request=>request.url.endsWith('/calendar'))).toBe(true)
    client.clear()
  })

})
