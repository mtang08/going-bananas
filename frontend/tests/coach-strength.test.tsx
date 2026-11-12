import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Coach } from '../src/pages/Coach'
import { Strength } from '../src/pages/Strength'
import { addDays, localDate } from '../src/api'

const today=localDate()
const dailyPayload={decision:'proceed_conditional',proposed_session:{mode:'run',purpose:'easy movement',duration_or_structure:'20 min',intensity_instruction:'Keep it easy'},alternative:{mode:'mobility',purpose:'gentle option',duration_or_structure:'10 min',intensity_instruction:'Stop if symptoms worsen'},planned_sessions:[{date:today,kind:'run',source:'run_cycle',optional:false},{date:today,kind:'strength',source:'recurring_schedule',optional:false}],additional_session_guidance:[{kind:'strength',optional:false,guidance:'Separate the full-body session if fatigue is high.'}],change_from_plan:'No confirmed plan',short_rationale:'Review current signals',confidence:{evidence:'moderate',athlete_applicability:'limited',decision:'conditional'},missing_or_stale_inputs:['Current symptoms not reported'],follow_up_observation:{what:'Check symptoms afterward',when:'Tomorrow'},references:{policy_ids:['P001'],evidence_ids:['E001'],sources:[]}}
const weeklyPayload={period_reviewed:{start:addDays(today,-13),end:today},actual_vs_planned:{summary:'Recorded work only',key_differences:[]},adaptation_signals:[],tolerance_signals:{favorable:[],concerning:[],delayed_symptom_findings:[]},strength_running_interactions:['Keep full-body lifting twice weekly'],next_cycle_proposal:{primary_target:'Preserve rhythm',sessions_or_placement_principles:['Run every other day'],changes_from_current_plan:[],preserved_commitments:[],dated_sessions:[{date:addDays(today,1),kind:'strength',source:'recurring_schedule',optional:false},{date:addDays(today,1),kind:'mobility',source:'recurring_schedule',optional:true}]},tradeoffs:[],uncertainties:['Unlinked plans are unknown'],what_would_change_the_recommendation:[],prior_advice_outcomes:['Accepted then completed'],references:{policy_ids:[],evidence_ids:[],sources:[]}}
const item=(kind:'daily'|'weekly',asOf=today,stale=false,supplemental_inputs={illness:'unknown',lower_body_soreness:'unknown',clinician_restriction:'unknown'})=>({id:`${kind}-${asOf}`,kind,as_of:asOf,generated_at:new Date().toISOString(),stale,stale_reasons:stale?['new check-in']:[],engine:'local_rules',knowledge_version:'1',supplemental_inputs,payload:kind==='daily'?dailyPayload:weeklyPayload,outcome:null as {status:string;effect?:string}|null})
const envelope=(data:unknown)=>({schema_version:'v1',data_revision:1,mode:'demo',data})
const calls:{url:string;method:string;body:unknown}[]=[]
let saved:ReturnType<typeof item>|null=null
let unavailable=false
let failOutcome=false
const respond=(data:unknown,ok=true)=>({ok,status:ok?200:409,json:async()=>ok?envelope(data):{error:{code:'stale_recommendation',message:'Regenerate after latest data change.'}}}) as Response
beforeEach(()=>{
  calls.length=0;saved=null;unavailable=false;failOutcome=false
  vi.stubGlobal('fetch',vi.fn(async(input:string,options?:RequestInit)=>{
    const url=String(input),method=options?.method||'GET',body=options?.body?JSON.parse(String(options.body)):null
    calls.push({url,method,body})
    if(url.includes('/coach/agent/revisions'))return respond({items:[],current_revision_id:null})
    if(url.includes('/coach/recommendations/')){
      if(failOutcome)return respond(null,false)
      if(saved)saved={...saved,outcome:{status:body.status,effect:body.effect}}
      return respond({status:body.status})
    }
    if(url.includes('/coach/daily')||url.includes('/coach/weekly')){
      const kind=url.includes('/daily')?'daily':'weekly',asOf=method==='POST'?body.as_of:new URL(url,'http://localhost').searchParams.get('as_of')||today
      if(method==='POST')saved=item(kind,asOf,false,kind==='daily'?{illness:body.illness,lower_body_soreness:body.lower_body_soreness,clinician_restriction:body.clinician_restriction}:{illness:'unknown',lower_body_soreness:'unknown',clinician_restriction:'unknown'})
      return respond({item:saved?.kind===kind&&saved.as_of===asOf?saved:null,knowledge:{available:!unavailable,version:'1'}})
    }
    if(url.includes('/strength/years'))return respond({years:[{year:2021,session_count:1},{year:Number(today.slice(0,4)),session_count:2}]})
    if(url.includes('/strength/history/'))return respond({workout_name:'Full body',date:'2021-06-07',sets:[{'Exercise Name':'Goblet Squat','Set Order':'1',Weight:'20',Reps:'8',Seconds:''}],resolution_state:'resolved'})
    if(url.includes('/strength/history'))return respond({session_count:2,known_duration_s:3600,unknown_duration_count:1,latest_imported_workout_date:today,imported_at:null,ambiguous_overlap_count:0,next_offset:null,sessions:[{id:'a',date:'2021-06-07',local_start:'10:00',duration_s:1800,exercise_count:1},{id:'b',date:'2021-06-08',local_start:'10:00',duration_s:null,exercise_count:2}]})
    return respond(null)
  }))
})
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
function mount(view:React.ReactNode){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});const result=render(<QueryClientProvider client={client}>{view}</QueryClientProvider>);const legacy=screen.queryByText('Local rule guidance · legacy');if(legacy)fireEvent.click(legacy);return result}

describe('Coach guidance',()=>{
  it('loads saved guidance without generating, then sends explicit unknown inputs and never writes a plan',async()=>{
    mount(<Coach onCheckin={()=>{}} onSetup={()=>{}}/>)
    await screen.findByText('A clear next step.')
    expect(calls.filter(c=>c.method==='POST')).toHaveLength(0)
    fireEvent.click(screen.getByRole('button',{name:'Generate daily guidance'}))
    await screen.findByText('Review current signals')
    expect(screen.getByText(/Run opportunity · repeating rhythm/)).toBeInTheDocument()
    expect(screen.getByText(/Full-body strength · repeating rhythm/)).toBeInTheDocument()
    expect(screen.getByText(/Separate the full-body session/)).toBeInTheDocument()
    expect(calls.find(c=>c.method==='POST')?.body).toMatchObject({as_of:today,illness:'unknown',lower_body_soreness:'unknown',clinician_restriction:'unknown'})
    expect(screen.getByText('Current symptoms not reported')).toBeInTheDocument()
    expect(calls.some(c=>c.url.includes('/plans'))).toBe(false)
  })
  it('warns when inputs change, blocks accepting stale guidance, and permits outcome follow-up',async()=>{
    saved=item('daily')
    mount(<Coach onCheckin={()=>{}} onSetup={()=>{}}/>)
    await screen.findByText('Review current signals')
    fireEvent.change(screen.getByLabelText('Illness'),{target:{value:'systemic'}})
    expect(screen.getByText(/controls above differ/)).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'Accept suggestion'})).toBeDisabled()
    fireEvent.click(screen.getByRole('button',{name:'Generate daily guidance'}))
    await waitFor(()=>expect(screen.getByRole('button',{name:'Accept suggestion'})).toBeEnabled())
    expect(calls.filter(c=>c.url.endsWith('/coach/daily')&&c.method==='POST').at(-1)?.body).toMatchObject({illness:'systemic'})
    fireEvent.click(screen.getByRole('button',{name:'Accept suggestion'}))
    await waitFor(()=>expect(calls.some(c=>c.url.includes('/outcome')&&c.method==='POST'&&(c.body as {status:string}).status==='accepted')).toBe(true))
    expect(calls.some(c=>c.url.includes('/plans'))).toBe(false)
  })
  it('shows saved supplemental inputs after reload and requires matching controls before deciding',async()=>{
    saved=item('daily',today,false,{illness:'none',lower_body_soreness:'usual',clinician_restriction:'none'})
    mount(<Coach onCheckin={()=>{}} onSetup={()=>{}}/>)
    await screen.findByText('Inputs used for saved guidance')
    expect(screen.getByText(/Illness: none · Lower-body soreness: usual · Clinician restrictions: none/)).toBeInTheDocument()
    expect(screen.getByRole('button',{name:'Accept suggestion'})).toBeDisabled()
    fireEvent.change(screen.getByLabelText('Illness'),{target:{value:'none'}})
    fireEvent.change(screen.getByLabelText('Lower-body soreness'),{target:{value:'usual'}})
    fireEvent.change(screen.getByLabelText('Clinician restrictions'),{target:{value:'none'}})
    expect(screen.getByRole('button',{name:'Accept suggestion'})).toBeEnabled()
  })
  it('keeps tomorrow provisional and shows weekly context and recorded outcomes',async()=>{
    mount(<Coach onCheckin={()=>{}} onSetup={()=>{}}/>)
    fireEvent.click(screen.getByRole('button',{name:'Tomorrow preview'}))
    fireEvent.click(screen.getByRole('button',{name:'Generate daily guidance'}))
    await screen.findByText('Review current signals')
    expect(screen.getByRole('button',{name:'Accept suggestion'})).toBeDisabled()
    expect(screen.getByRole('button',{name:'Decline'})).toBeDisabled()
    fireEvent.click(screen.getByText('Record what happened'))
    expect(screen.getByRole('button',{name:'completed'})).toBeDisabled()
    fireEvent.click(screen.getByRole('button',{name:'Weekly review'}))
    fireEvent.click(screen.getByRole('button',{name:'Generate weekly review'}))
    await screen.findByText('Preserve rhythm')
    expect(screen.getByText('Keep full-body lifting twice weekly')).toBeInTheDocument()
    expect(screen.getByText(/Optional mobility/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Previous advice and outcomes'))
    expect(screen.getByText('Accepted then completed')).toBeInTheDocument()
  })
  it('reports unavailable knowledge and outcome errors',async()=>{
    unavailable=true;saved=item('daily')
    mount(<Coach onCheckin={()=>{}} onSetup={()=>{}}/>)
    await screen.findByText(/research package is missing/)
    expect(screen.getByRole('button',{name:'Generate daily guidance'})).toBeDisabled()
  })
  it('blocks stale decisions and reports failed outcome writes',async()=>{
    saved=item('daily',today,true)
    mount(<Coach onCheckin={()=>{}} onSetup={()=>{}}/>)
    await screen.findByText(/needs a fresh review/)
    expect(screen.getByRole('button',{name:'Accept suggestion'})).toBeDisabled()
    expect(screen.getByRole('button',{name:'Decline'})).toBeDisabled()
    fireEvent.click(screen.getByRole('button',{name:'Generate daily guidance'}))
    await waitFor(()=>expect(screen.getByRole('button',{name:'Accept suggestion'})).toBeEnabled())
    failOutcome=true
    fireEvent.click(screen.getByRole('button',{name:'Accept suggestion'}))
    await screen.findByText('Regenerate after latest data change.')
  })
  it('records acceptance then later completion without writing a calendar plan',async()=>{
    saved=item('daily')
    mount(<Coach onCheckin={()=>{}} onSetup={()=>{}}/>)
    await screen.findByText('Review current signals')
    fireEvent.click(screen.getByRole('button',{name:'Accept suggestion'}))
    await screen.findByText(/Recorded: accepted/)
    fireEvent.click(screen.getByText('Record what happened'))
    fireEvent.change(screen.getByLabelText('How did it work?'),{target:{value:'helpful'}})
    fireEvent.click(screen.getByRole('button',{name:'completed'}))
    await screen.findByText(/Recorded: completed · helpful/)
    expect(calls.filter(c=>c.url.includes('/outcome')&&c.method==='POST').map(c=>(c.body as {status:string}).status)).toEqual(['accepted','completed'])
    expect(calls.some(c=>c.url.includes('/plans'))).toBe(false)
  })
})

describe('Strong history',()=>{
  it('uses recorded years and chronological pages, with source-faithful set detail',async()=>{
    mount(<Strength/>)
    const select=await screen.findByLabelText('Year')
    await waitFor(()=>expect(within(select).getByRole('option',{name:'2021'})).toBeInTheDocument())
    fireEvent.change(select,{target:{value:'2021'}})
    const table=await screen.findByRole('table')
    const rows=within(table).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('Jun 7, 2021')
    expect(rows[2]).toHaveTextContent('Jun 8, 2021')
    fireEvent.click(within(rows[1]).getByRole('button'))
    await screen.findByText('Goblet Squat')
    expect(screen.getByText(/units unconfirmed/)).toBeInTheDocument()
    expect(screen.getByText(/change from combined to single-dumbbell/)).toBeInTheDocument()
  })
})
