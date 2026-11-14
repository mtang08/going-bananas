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
  const path = join(proposalDir,`p1-${randomUUID()}.json`)
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
async function review(page:Page,id:string) {
  await page.goto(`/#proposal/${id}`)
  await expect(page.getByRole('heading',{name:'Review proposal'})).toBeVisible()
}

let persistingId = ''
let patchId = ''

test.beforeAll(async ({request})=>{
  const profile = await request.get('/api/v1/profile')
  expect(profile.ok()).toBe(true)
  const envelope = await profile.json()
  expect(envelope.mode).toBe('demo')
  expect(envelope.data.planning_authority).toBe('calendar')
})

test('p1: repeated fatigue raises a caution finding',async ({page,request})=>{
  test.setTimeout(120_000)
  const today=(await calendar(request)).today
  const history=await data(await request.get(`/api/v1/calendar?start=${day(today,-13)}&end=${day(today,-1)}`))
  const easy=history.sessions.find((item:any)=>item.local_date===day(today,-8) && item.recipe_id==='REC001')
  const completion=history.completions.find((item:any)=>item.session_uid===easy?.session_uid && item.activity_id)
  expect(completion,'seeded easy run on T-8').toBeTruthy()
  const activityId=completion.activity_id
  await data(await request.put(`/api/v1/activities/${activityId}/rpe`,{headers:local,data:{rpe:7}}))
  for(const h of [26,1]){
    const response=await request.post('/api/v1/v2/checkins',{headers:local,data:{
      kind:'exception',fatigue:8,illness:'none',gait_change:'no',context_tags:[],symptoms:[],
      activity_id:null,prompt_id:null,note:null,idempotency_key:randomUUID(),
      observed_at:new Date(Date.now()-h*3600_000).toISOString(),
    }})
    expect(response.status()).toBe(201)
  }
  const ex=await data(await request.get('/api/v1/exceptions'))
  const persisting=ex.findings.find((item:any)=>item.rule_code==='FATIGUE_PERSISTING' && item.status==='open' && item.severity==='caution')
  expect(persisting).toBeTruthy()
  persistingId=persisting.id
  expect(ex.findings.some((item:any)=>item.rule_code==='RPE_ABOVE_INTENT' && item.entity_key===`activity:${activityId}`)).toBe(true)
  expect(ex.review_recommended.some((item:any)=>item.operation==='exception_review')).toBe(true)
  await page.goto('/')
  await expect(page.locator('[data-testid="attention-row"][data-kind="finding"]').filter({hasText:'Fatigue and recovery'}).first()).toContainText('Caution')
  await expect(page.locator('[data-testid="attention-row"][data-kind="recommendation"]').filter({hasText:'Exception review'}).first().getByRole('button',{name:'Copy prompt'})).toBeVisible()
  await expect(page.getByText(/Logged for Sunday review \(\d+\)/)).toBeVisible()
})

test('p1: exception review patches one committed session',async ({page,request})=>{
  test.setTimeout(120_000)
  for(const item of (await data(await request.get('/api/v1/coach/proposals?status=open'))).items){
    await data(await request.delete(`/api/v1/coach/proposals/${item.id}?expected_revision=${item.revision}`,{headers:local}))
  }
  const current=await calendar(request)
  const run2=runOn(current,2)
  const snap=snapshot('exception_review')
  const exception={finding_ids:[persistingId],category:'accumulated_fatigue',severity:'caution',confidence:'moderate',
    triggering_evidence:'Fatigue 8 on two days in a row',relevant_context:null,ladder_level:'next_session',
    patch_window:{start:current.today,end:day(current.today,2)},unchanged:[],reassess_on:current.today,
    monitor:['Morning fatigue'],return_criteria:['Fatigue below 6 on two mornings'],
    escalate_criteria:['Fatigue 8 or higher through the weekend']}
  const submitted=submit(documentFrom(snap,[change('c1',run2,{planned_duration_s:run2.planned_duration_s-600})],
    `P1 exception ${randomUUID().slice(0,8)}`,{exception}))
  expect(submitted.code,JSON.stringify(submitted.output)).toBe(0)
  expect(submitted.output.status).toBe('pending')
  await review(page,submitted.output.proposal_id)
  const details=page.getByTestId('proposal-exception')
  await expect(details).toContainText('Next session only')
  await expect(details).toContainText('Fatigue and recovery')
  await expect(details).toContainText('Caution')
  await page.getByRole('checkbox',{name:'Accept change c1'}).check()
  await page.getByRole('button',{name:'Accept selected'}).click()
  await expect(page.getByRole('status').filter({hasText:/Accepted — calendar version/})).toBeVisible()
  const detail=await data(await request.get(`/api/v1/coach/proposals/${submitted.output.proposal_id}`))
  expect(detail.patch).toMatchObject({status:'open',reassess_on:current.today})
  patchId=detail.patch.id
  await page.goto('/')
  await expect(page.locator(`[data-testid="strip-day"][data-date="${day(current.today,2)}"]`).getByTestId('patch-badge')).toContainText('Patched · reassess')
  await page.goto('/#calendar')
  await expect(page.locator(`[data-testid="session-row"][data-date="${day(current.today,2)}"]`).getByTestId('patch-badge').first()).toBeVisible()
})

test('p1: resolving the patch clears the badge and the finding',async ({page,request})=>{
  const today=(await calendar(request)).today
  await page.goto('/')
  const patch=page.locator('[data-testid="attention-row"][data-kind="patch"]').first()
  await expect(patch).toContainText('Reassess due')
  await patch.getByRole('button',{name:'Mark resolved'}).click()
  await expect(page.locator('[data-testid="attention-row"][data-kind="patch"]')).toHaveCount(0)
  await expect(page.locator(`[data-testid="strip-day"][data-date="${day(today,2)}"]`).getByTestId('patch-badge')).toHaveCount(0)
  const ex=await data(await request.get('/api/v1/exceptions?include=recent'))
  expect(ex.patches.find((item:any)=>item.id===patchId)).toMatchObject({status:'resolved',resolved_by:'athlete'})
  expect(ex.findings.find((item:any)=>item.id===persistingId)?.status).toBe('resolved')
})

test('p1: manual benchmark match recommends a block review',async ({page,request})=>{
  test.setTimeout(120_000)
  const today=(await calendar(request)).today
  const active=await data(await request.get('/api/v1/blocks/active'))
  expect(active.benchmark.kind).toBe('time_trial')
  expect(active.benchmark_status.status).toBe('pending')
  const run=(await data(await request.get(`/api/v1/activities?start_date=${day(today,-1)}&end_date=${today}&sport=running`))).items[0]
  expect(run).toBeTruthy()
  await page.goto('/#block')
  const card=page.getByTestId('block-benchmark')
  await expect(card.getByTestId('benchmark-status')).toContainText('Pending')
  await card.getByLabel('Choose activity').selectOption(run.id)
  await expect(card.getByTestId('benchmark-status')).toContainText('Completed')
  await expect(card.getByTestId('benchmark-match')).toContainText('Chosen by you')
  const ex=await data(await request.get('/api/v1/exceptions'))
  expect(ex.findings.some((item:any)=>item.rule_code==='BLOCK_BENCHMARK_COMPLETED' && item.status==='open')).toBe(true)
  expect(ex.review_recommended).toContainEqual(expect.objectContaining({operation:'review_training_block',
    reason:'Block benchmark complete — review the block and recalibrate',
    prompt:'Use $going-bananas-coach for a block review. Review the block benchmark.'}))
  await page.goto('/')
  await expect(page.locator('[data-testid="attention-row"][data-kind="recommendation"]').filter({hasText:'Block benchmark complete'}).first()).toBeVisible()
  await expect(page.getByTestId('block-line')).toContainText('Completed')
})
