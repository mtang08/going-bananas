import { execFileSync } from 'node:child_process'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type APIResponse, type Page } from '../frontend/node_modules/@playwright/test'

// This suite runs against the manager's disposable demo database and port 18000.
test.describe.configure({ mode: 'serial' })
const repoRoot = resolve(__dirname, '..')
const backend = join(repoRoot, 'backend')
const coachScript = join(repoRoot, 'scripts', 'with-mode')
const proposalDir = join(repoRoot, 'private', 'demo', 'coach', 'proposals')
const local = { 'X-Local-Request': '1' }
const day = (today:string, offset:number) => {
  const value = new Date(`${today}T12:00:00Z`)
  value.setUTCDate(value.getUTCDate()+offset)
  return value.toISOString().slice(0,10)
}
const data = async (response:APIResponse) => {
  expect(response.ok(), await response.text()).toBe(true)
  return (await response.json()).data
}
const errorCode = async (response:APIResponse) => (await response.json()).error.code as string

type CoachCall = {code:number; output:any; stderr:string}
function coach(...args:string[]):CoachCall {
  const argv = ['demo','uv','run','--directory',backend,'python','-m','app.cli','coach',...args]
  try {
    const stdout = execFileSync(coachScript,argv,{cwd:repoRoot,encoding:'utf8',timeout:120_000})
    return {code:0,output:JSON.parse(stdout),stderr:''}
  } catch (cause) {
    const error = cause as {status?:number;stdout?:string|Buffer;stderr?:string|Buffer}
    const stdout = String(error.stdout ?? '').trim()
    return {code:error.status ?? 1,output:stdout?JSON.parse(stdout):null,stderr:String(error.stderr ?? '')}
  }
}
function snapshot(operation:string) {
  const result = coach('snapshot','--operation',operation)
  expect(result.code,result.stderr).toBe(0)
  expect(result.output.snapshot_id).toMatch(/^[0-9a-f-]{36}$/)
  return result.output
}
function proposalFile(document:object):string {
  mkdirSync(proposalDir,{recursive:true,mode:0o700})
  const path = join(proposalDir,`p0b-${randomUUID()}.json`)
  writeFileSync(path,JSON.stringify(document),{encoding:'utf8',mode:0o600,flag:'wx'})
  return path
}
function submit(document:object) {
  return coach('submit','--file',proposalFile(document))
}
function documentFrom(snapshotResult:any, changes:any[], summary:string, extras:Record<string,unknown>={}) {
  const meta = snapshotResult.payload.snapshot_meta
  return {schema_version:'coach_proposal.v1',operation:meta.operation,snapshot_id:snapshotResult.snapshot_id,
    base_calendar_version:meta.calendar_version,base_block_version_id:meta.block_version_id,
    summary,rationale:'Review the current training evidence before changing the plan.',
    confidence:{decision:'moderate',evidence:'moderate',data:'moderate'},changes,preserved:[],
    evidence_ids:['E-AER-01'],policy_ids:['P001'],recipe_ids:['REC001'],
    skill_version:'running-coach.v1',...extras}
}
function runOn(calendar:any, offset:number):any {
  const found = calendar.sessions.find((item:any)=>item.local_date===day(calendar.today,offset) && item.kind==='run')
  expect(found,`Expected a seeded run on T+${offset}`).toBeTruthy()
  return found
}
function change(id:string, session:any, after:Record<string,unknown>) {
  return {change_id:id,op:'modify',session_uid:session.session_uid,after,reason:'Synthetic reviewed adjustment'}
}
async function calendar(request:APIRequestContext) { return data(await request.get('/api/v1/calendar')) }
async function decision(request:APIRequestContext,id:string,body:object) {
  return request.post(`/api/v1/coach/proposals/${id}/decision`,{headers:local,data:body})
}
async function review(page:Page,id:string) {
  await page.goto(`/#proposal/${id}`)
  await expect(page.getByRole('heading',{name:'Review proposal'})).toBeVisible()
}

let weekly:{id:string;before:any;head:number;result:any;selection:any;run2:any;run4:any;run8:any}|undefined
let emptyHead:number|undefined

test.beforeAll(async ({request})=>{
  const profile = await request.get('/api/v1/profile')
  expect(profile.ok()).toBe(true)
  const envelope = await profile.json()
  expect(envelope.mode).toBe('demo')
  expect(envelope.data.planning_authority).toBe('calendar')
})

test('p0b: weekly untick one accept rest',async ({page,request})=>{
  test.setTimeout(120_000)
  const before=await calendar(request)
  const run2=runOn(before,2),run4=runOn(before,4),run8=runOn(before,8)
  const snap=snapshot('review_rolling_plan')
  const summary=`P0-B weekly ${randomUUID().slice(0,8)}`
  const changes=[change('c1',run2,{planned_duration_s:run2.planned_duration_s+300}),
    change('c2',run4,{intent:'Synthetic proposed intent'}),
    change('c3',run8,{planned_duration_s:run8.planned_duration_s-300})]
  expect(run8.planned_duration_s).toBeGreaterThan(300)
  const submitted=submit(documentFrom(snap,changes,summary))
  expect(submitted.code,JSON.stringify(submitted.output)).toBe(0)
  expect(submitted.output.status).toBe('pending')
  expect((await calendar(request)).head).toBe(before.head)
  await page.goto('/')
  await expect(page.getByRole('heading',{name:'Pending proposal'})).toBeVisible()
  await page.locator('.pending-proposals article').filter({hasText:summary}).getByRole('link',{name:'Review proposal'}).click()
  await expect(page.getByRole('heading',{name:'Review proposal'})).toBeVisible()
  await page.getByRole('checkbox',{name:'Accept change c1'}).check()
  await page.getByRole('checkbox',{name:'Accept change c2'}).check()
  await page.getByRole('checkbox',{name:'Accept change c2'}).uncheck()
  await page.getByRole('checkbox',{name:'Accept change c3'}).check()
  await page.getByRole('button',{name:'Accept selected'}).click()
  await expect(page.getByRole('status').filter({hasText:/Accepted — calendar version/})).toBeVisible()
  const detail=await data(await request.get(`/api/v1/coach/proposals/${submitted.output.proposal_id}`))
  expect(detail.status).toBe('partially_accepted')
  expect(detail.changes.map((item:any)=>[item.change_id,item.decision])).toEqual([['c1','accepted'],['c2','rejected'],['c3','accepted']])
  const after=await calendar(request)
  expect(after.head).toBe(before.head+1)
  const versions=await data(await request.get('/api/v1/calendar/versions?limit=1'))
  expect(versions.items[0]).toMatchObject({number:after.head,kind:'proposal_accept',actor:'coach',proposal_id:submitted.output.proposal_id})
  const updated=(session:any)=>after.sessions.find((row:any)=>row.session_uid===session.session_uid)
  expect(updated(run2)).toMatchObject({planned_duration_s:run2.planned_duration_s+300,revision:run2.revision+1,changed_by_version:after.head})
  expect(updated(run8)).toMatchObject({planned_duration_s:run8.planned_duration_s-300,revision:run8.revision+1,changed_by_version:after.head})
  expect(updated(run4)).toMatchObject({intent:run4.intent,revision:run4.revision})
  const replayBody={idempotency_key:randomUUID(),expected_head:0,accept_change_ids:['c3','c1'],reject_change_ids:['c2'],accept_block_change:false,accept_anchor_changes:[]}
  const replay=await decision(request,submitted.output.proposal_id,replayBody)
  expect(replay.status()).toBe(200)
  expect((await data(replay)).calendar_version).toBe(after.head)
  expect((await calendar(request)).head).toBe(after.head)
  weekly={id:submitted.output.proposal_id,before,head:after.head,result:detail,selection:replayBody,run2,run4,run8}
})

test('p0b: next snapshot carries outcomes',async ({request})=>{
  test.setTimeout(120_000)
  expect(weekly).toBeDefined()
  const next=snapshot('review_rolling_plan')
  const prior=next.payload.prior_decisions.find((item:any)=>item.proposal_id===weekly!.id)
  expect(prior).toBeTruthy()
  expect(prior.changes.map((item:any)=>[item.change_id,item.decision])).toEqual([['c1','accepted'],['c2','rejected'],['c3','accepted']])
  expect(next.payload.calendar.sessions.some((item:any)=>item.session_uid===weekly!.run2.session_uid && item.planned_duration_s===weekly!.run2.planned_duration_s+300)).toBe(true)
  expect((await calendar(request)).head).toBe(weekly!.head)
})

test('p0b: empty acknowledgement preserves undo',async ({page,request})=>{
  test.setTimeout(120_000)
  expect(weekly).toBeDefined()
  const before=await calendar(request)
  const snap=snapshot('review_rolling_plan')
  const submitted=submit(documentFrom(snap,[],`P0-B no change ${randomUUID().slice(0,8)}`))
  expect(submitted.code,JSON.stringify(submitted.output)).toBe(0)
  await review(page,submitted.output.proposal_id)
  await page.getByRole('button',{name:'Accept (no changes)'}).click()
  await expect(page.getByRole('status').filter({hasText:'Decision recorded — calendar unchanged'})).toBeVisible()
  const detail=await data(await request.get(`/api/v1/coach/proposals/${submitted.output.proposal_id}`))
  expect(detail.status).toBe('accepted')
  expect(detail.decision_result.calendar_version).toBeNull()
  const after=await calendar(request)
  expect(after.head).toBe(before.head)
  expect(after.undo?.target_version).toBe(weekly!.before.head)
  expect(after.undo?.eligible).toBe(true)
  emptyHead=after.head
})

test('p0b: protected undo',async ({page,request})=>{
  test.setTimeout(120_000)
  expect(weekly).toBeDefined()
  expect(emptyHead).toBeDefined()
  const current=await calendar(request)
  const wideBefore=await data(await request.get(`/api/v1/calendar?start=${day(current.today,-14)}&end=${day(current.today,13)}`))
  const protectedRows=wideBefore.sessions.filter((row:any)=>row.locked || row.local_date<current.today)
  await page.goto('/#calendar')
  const target=weekly!.before.head
  const version=page.getByTestId('version-row').filter({hasText:`v${target} ·`})
  await version.getByRole('button',{name:'Restore',exact:true}).click()
  await version.getByRole('button',{name:'Confirm restore'}).click()
  await expect.poll(async ()=>(await calendar(request)).head,{timeout:20_000}).toBe(current.head+1)
  const after=await calendar(request)
  const wideAfter=await data(await request.get(`/api/v1/calendar?start=${day(current.today,-14)}&end=${day(current.today,13)}`))
  expect(after.sessions.find((row:any)=>row.session_uid===weekly!.run2.session_uid)?.planned_duration_s).toBe(weekly!.run2.planned_duration_s)
  expect(after.sessions.find((row:any)=>row.session_uid===weekly!.run8.session_uid)?.planned_duration_s).toBe(weekly!.run8.planned_duration_s)
  for(const old of protectedRows){
    const preserved=wideAfter.sessions.find((row:any)=>row.session_uid===old.session_uid)
    expect(preserved).toMatchObject({local_date:old.local_date,revision:old.revision,locked:old.locked})
  }
  const latest=await data(await request.get('/api/v1/calendar/versions?limit=1'))
  expect(latest.items[0]).toMatchObject({kind:'rollback',actor:'user',restored_from_number:target})
})

test('p0b: daily exception scope',async ({page,request})=>{
  test.setTimeout(120_000)
  const checkin=await request.post('/api/v1/v2/checkins',{headers:local,data:{
    idempotency_key:randomUUID(),kind:'exception',observed_at:new Date().toISOString(),
    fatigue:7,illness:'none',gait_change:'yes',context_tags:[],symptoms:[],activity_id:null,prompt_id:null,note:null,
  }})
  expect(checkin.status()).toBe(201)
  const guidance=await data(await request.post('/api/v1/coach/v2/daily/request',{headers:local,data:{}}))
  expect(guidance.coach_review_suggested).toBe(true)
  const current=await calendar(request)
  const run2=runOn(current,2),run4=runOn(current,4)
  const snap=snapshot('proceed_or_modify_today')
  const reduced=submit(documentFrom(snap,[change('c1',run2,{planned_duration_s:run2.planned_duration_s-600})],`P0-B daily reduce ${randomUUID().slice(0,8)}`))
  expect(reduced.code,JSON.stringify(reduced.output)).toBe(0)
  expect(reduced.output.status).toBe('pending')
  const outside=submit(documentFrom(snap,[change('c1',run4,{intent:'Outside daily scope'})],`P0-B daily outside ${randomUUID().slice(0,8)}`))
  expect(outside.code).toBe(2)
  expect(outside.output.errors[0]).toMatchObject({code:'V5.out_of_scope',path:'changes.0'})
  const increase=submit(documentFrom(snap,[change('c1',run2,{planned_duration_s:run2.planned_duration_s+600})],`P0-B daily increase ${randomUUID().slice(0,8)}`))
  expect(increase.code).toBe(2)
  expect(increase.output.errors[0]).toMatchObject({code:'V12.safety_guard',path:'changes.0'})
  expect((await calendar(request)).head).toBe(current.head)
  await page.goto('/')
  await expect(page.getByText(/Coach review suggested/)).toBeVisible()
  const rejected=await decision(request,reduced.output.proposal_id,{idempotency_key:randomUUID(),expected_head:current.head,
    accept_change_ids:[],reject_change_ids:['c1'],accept_block_change:false,accept_anchor_changes:[]})
  expect(rejected.status()).toBe(200)
})

test('p0b: stale cannot be accepted',async ({page,request})=>{
  test.setTimeout(120_000)
  const before=await calendar(request)
  const target=runOn(before,2)
  const moving=runOn(before,4)
  const snap=snapshot('review_rolling_plan')
  const submitted=submit(documentFrom(snap,[change('c1',target,{intent:'Pending before manual edit'})],`P0-B stale ${randomUUID().slice(0,8)}`))
  expect(submitted.code).toBe(0)
  const movedDate=day(moving.local_date,1)
  const edit=await request.post('/api/v1/calendar/edits',{headers:local,data:{expected_head:before.head,
    edits:[{op:'move',session_uid:moving.session_uid,fields:{local_date:movedDate}}]}})
  expect(edit.status()).toBe(201)
  expect((await data(edit)).stale_proposals).toContain(submitted.output.proposal_id)
  await review(page,submitted.output.proposal_id)
  await expect(page.getByText(/This proposal is stale/)).toBeVisible()
  await expect(page.getByRole('button',{name:'Accept selected'})).toBeDisabled()
  const head=(await calendar(request)).head
  const response=await decision(request,submitted.output.proposal_id,{idempotency_key:randomUUID(),expected_head:head,
    accept_change_ids:['c1'],reject_change_ids:[],accept_block_change:false,accept_anchor_changes:[]})
  expect(response.status()).toBe(409)
  expect(await errorCode(response)).toBe('proposal_stale')
  expect((await calendar(request)).head).toBe(head)
})

test('p0b: source-only drift and invalid subset',async ({request})=>{
  test.setTimeout(120_000)
  const before=await calendar(request)
  const target=runOn(before,2)
  const snap=snapshot('review_rolling_plan')
  const submitted=submit(documentFrom(snap,[change('c1',target,{intent:'Source freshness candidate'})],`P0-B source drift ${randomUUID().slice(0,8)}`))
  expect(submitted.code).toBe(0)
  const symptom=await request.post('/api/v1/v2/checkins',{headers:local,data:{
    idempotency_key:randomUUID(),kind:'exception',observed_at:new Date().toISOString(),
    fatigue:null,illness:'none',gait_change:'no',context_tags:[],
    symptoms:[{site:'calf',side:'left',severity:2,timing:'during'}],activity_id:null,prompt_id:null,note:null,
  }})
  expect(symptom.status()).toBe(201)
  expect((await calendar(request)).head).toBe(before.head)
  const stale=await decision(request,submitted.output.proposal_id,{idempotency_key:randomUUID(),expected_head:before.head,
    accept_change_ids:['c1'],reject_change_ids:[],accept_block_change:false,accept_anchor_changes:[]})
  expect(stale.status()).toBe(409)
  expect(await errorCode(stale)).toBe('stale_evidence')
  expect((await calendar(request)).head).toBe(before.head)

  const current=await calendar(request)
  const run8=runOn(current,8)
  const fresh=snapshot('review_rolling_plan')
  const replacement={change_id:'c2',op:'add',reason:'Replace the same on-cycle session',after:{
    local_date:run8.local_date,kind:'run',intent:'Custom easy replacement',custom:true,
    structure:[{type:'work',duration_type:'time',duration_value:600}],
  }}
  const subset=submit(documentFrom(fresh,[{change_id:'c1',op:'delete',session_uid:run8.session_uid,reason:'Replace run'},replacement],
    `P0-B subset ${randomUUID().slice(0,8)}`))
  expect(subset.code,JSON.stringify(subset.output)).toBe(0)
  const invalid=await decision(request,subset.output.proposal_id,{idempotency_key:randomUUID(),expected_head:current.head,
    accept_change_ids:['c2'],reject_change_ids:['c1'],accept_block_change:false,accept_anchor_changes:[]})
  expect(invalid.status()).toBe(422)
  expect(await errorCode(invalid)).toBe('proposal_invalid_subset')
  expect((await calendar(request)).head).toBe(current.head)
  const reject=await decision(request,subset.output.proposal_id,{idempotency_key:randomUUID(),expected_head:current.head,
    accept_change_ids:[],reject_change_ids:['c1','c2'],accept_block_change:false,accept_anchor_changes:[]})
  expect(reject.status()).toBe(200)
  expect((await data(reject)).status).toBe('rejected')
  expect((await calendar(request)).head).toBe(current.head)
})

test('p0b: block start',async ({page,request})=>{
  test.setTimeout(120_000)
  const active=await data(await request.get('/api/v1/blocks/active'))
  expect(active).toBeNull()
  const before=await calendar(request)
  const snap=snapshot('review_training_block')
  const blockChange={decision:'start',block_uid:null,version_fields:{
    status:'active',objective:'Synthetic aerobic base',rationale:'Review the current plan and build steadily.',
    maintained_qualities:['easy volume'],non_goals:['racing'],eligible_recipe_ids:['REC001','REC002','REC003'],
    progression_dimension:'duration',constraints:[],start_date:before.today,review_date:day(before.today,42),
    completion_indicators:['consistent sessions'],early_review_triggers:['symptoms'],objective_status:'unresolved',
  }}
  const submitted=submit(documentFrom(snap,[],`P0-B block ${randomUUID().slice(0,8)}`,{block_change:blockChange}))
  expect(submitted.code,JSON.stringify(submitted.output)).toBe(0)
  await review(page,submitted.output.proposal_id)
  await page.getByRole('checkbox',{name:'Accept block change'}).check()
  await page.getByRole('button',{name:'Accept selected'}).click()
  await expect(page.getByRole('status').filter({hasText:'Decision recorded — calendar unchanged'})).toBeVisible()
  const detail=await data(await request.get(`/api/v1/coach/proposals/${submitted.output.proposal_id}`))
  expect(detail.status).toBe('accepted')
  expect(detail.decision_result.block_version_id).toBeTruthy()
  expect((await calendar(request)).head).toBe(before.head)
  const current=await data(await request.get('/api/v1/blocks/active'))
  expect(current).toMatchObject({objective:'Synthetic aerobic base',version:1,proposal_id:submitted.output.proposal_id})
  await page.goto('/#block')
  await expect(page.getByRole('heading',{name:'Training block'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'Synthetic aerobic base'})).toBeVisible()
  await expect(page.getByRole('heading',{name:'Version 1 · active'})).toBeVisible()
  const history=await data(await request.get(`/api/v1/blocks/${current.block_uid}/history`))
  expect(history.items).toHaveLength(1)
})
