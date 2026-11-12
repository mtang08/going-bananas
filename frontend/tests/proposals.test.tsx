import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProposalReview } from '../src/pages/ProposalReview'
import type { ProposalDecision, ProposalDetail } from '../src/api/types/coach'
import type { PlannedStep } from '../src/api/types/calendar'

let proposal:ProposalDetail
let authority='calendar'
let failure:'network'|'subset'|'stale'|'revision'|null=null
let failReload=false
let writes:ProposalDecision[]=[]
let deletes:number[]=[]
const clients:QueryClient[]=[]
beforeEach(()=>{
  authority='calendar';failure=null;failReload=false;writes=[];deletes=[]
  proposal={id:'p1',operation:'review_rolling_plan',status:'pending',submitted_at:'2026-11-12T12:00:00Z',decided_at:null,
    summary:'Adjust the next week',rationale:'Keep the run manageable',confidence:{decision:'moderate',evidence:'high',data:'moderate'},
    base_calendar_version:7,base_block_version_id:null,snapshot_id:'snapshot',head:7,is_current:true,revision:1,revisions:[],
    evidence_ids:['E-AER-01'],policy_ids:['P001'],recipe_ids:['REC001'],follow_up:'Review after the run',escalation:null,
    block_change:null,anchor_changes:[],validation_errors:[],skill_version:'running-coach.v1',
    changes:['c1','c2','c3'].map((id,index)=>({change_id:id,op:'modify',session_uid:`s${index}`,
      before:{intent:'Easy',planned_duration_s:1800,structure:null},after:{planned_duration_s:2100},current:{intent:'Easy'},
      reason:`Adjustment ${index+1}`,decision:'pending',material_flags:[]}))}
  vi.stubGlobal('fetch',vi.fn(async(input:string,options?:RequestInit)=>{
    const url=String(input)
    if(options?.method==='DELETE'){
      deletes.push(Number(new URL(url,'http://localhost').searchParams.get('expected_revision')))
      if(failure==='revision')return {ok:false,status:409,json:async()=>({error:{code:'proposal_revision_conflict',message:'Revision changed',fields:[]}})}
      proposal={...proposal,status:'discarded'}
      return {ok:true,json:async()=>({schema_version:'v1',mode:'demo',data_revision:2,data:{proposal_id:'p1',revision:proposal.revision,status:'discarded'}})}
    }
    if(options?.method==='POST'){
      const body=JSON.parse(String(options.body)) as ProposalDecision;writes.push(body)
      if(failure==='network')throw new Error('offline')
      if(failure)return {ok:false,status:failure==='stale'||failure==='revision'?409:422,json:async()=>({error:{code:failure==='stale'?'stale_evidence':failure==='revision'?'proposal_revision_conflict':'proposal_invalid_subset',message:'Review the selected changes',fields:[{path:'changes.1',message:'Preserve strength count'}]}})}
      const status=body.accept_change_ids.length===0&&proposal.changes.length?'rejected':body.reject_change_ids.length?'partially_accepted':'accepted'
      proposal={...proposal,status,is_current:false,changes:proposal.changes.map(change=>({...change,decision:body.accept_change_ids.includes(change.change_id)?'accepted':'rejected'}))}
      return {ok:true,json:async()=>({schema_version:'v1',mode:'demo',data_revision:2,data:{proposal_id:'p1',status,calendar_version:body.accept_change_ids.length?8:null,block_version_id:null,anchor_keys:[],stale_proposals:[]}})}
    }
    if(failReload && url.includes('/coach/proposals/')) throw new Error('offline')
    return {ok:true,json:async()=>({schema_version:'v1',mode:'demo',data_revision:1,data:url.endsWith('/profile')?{planning_authority:authority}:proposal})}
  }))
})
afterEach(()=>{cleanup();clients.forEach(client=>client.clear());clients.length=0;vi.unstubAllGlobals()})
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});clients.push(client);return render(<QueryClientProvider client={client}><ProposalReview proposalId="p1"/></QueryClientProvider>)}
async function select(...ids:string[]){for(const id of ids)fireEvent.click(await screen.findByLabelText(`Accept change ${id}`))}

it('renders coach paragraphs and bullets safely with confidence collapsed and follow-up after the plan',async()=>{
  proposal.summary='Keep this week manageable.\n\nPreserve the confirmed strength days.'
  proposal.rationale='- Recent runs felt harder. [E-AER-01]\n- Hold volume steady.'
  proposal.changes[0].reason='<script>alert("test")</script>'
  const {container}=mount()
  await screen.findByText('Keep this week manageable.')
  expect(screen.getByText('Preserve the confirmed strength days.').tagName).toBe('P')
  expect(screen.getByText('Recent runs felt harder.').tagName).toBe('LI')
  expect(screen.getByText('Confidence details').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText('<script>alert("test")</script>')).toBeInTheDocument()
  expect(container.querySelector('script')).toBeNull()
  const table=screen.getByRole('table',{name:'Proposed plan changes'})
  expect(table.compareDocumentPosition(screen.getByText('Review after the run')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

it('requires individual review and submits complete partial selection',async()=>{
  mount();expect(await screen.findByLabelText('Accept change c1')).not.toBeChecked();expect(writes).toHaveLength(0)
  expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled()
  await select('c1','c3');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText('Accepted — calendar version 8')
  expect(writes[0]).toEqual({idempotency_key:expect.any(String),expected_head:7,expected_revision:1,accept_change_ids:['c1','c3'],reject_change_ids:['c2'],accept_block_change:false,accept_anchor_changes:[]})
  expect(screen.queryByRole('button',{name:'Accept selected'})).not.toBeInTheDocument()
})
it('retains selections and shows structured subset errors',async()=>{
  failure='subset';mount();await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText('changes.1: Preserve strength count');expect(screen.getByLabelText('Accept change c1')).toBeChecked()
})
it('retries the exact frozen request after a lost response',async()=>{
  failure='network';mount();await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText(/Cannot reach/);failure=null;fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await waitFor(()=>expect(writes).toHaveLength(2));expect(writes[1]).toEqual(writes[0])
})
it('creates a new request key after editing the selection',async()=>{
  failure='subset';mount();await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText('changes.1: Preserve strength count');await select('c3');failure=null
  fireEvent.click(screen.getByRole('button',{name:'Accept selected'}));await waitFor(()=>expect(writes).toHaveLength(2))
  expect(writes[1].idempotency_key).not.toBe(writes[0].idempotency_key)
})
it('disables stale proposals and retains their saved diff',async()=>{
  proposal.is_current=false;mount();await screen.findByText(/This proposal is stale/)
  expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled();expect(screen.getAllByText('Easy').length).toBeGreaterThan(0)
})
it('blocks further acceptance after a source conflict',async()=>{
  failure='stale';mount();await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText(/This proposal is stale/);expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled()
})
it('requires an explicit reload after a revision conflict and discards old selections',async()=>{
  failure='revision';mount();await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText(/edited while you reviewed it/)
  expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled()
  proposal={...proposal,revision:2,revisions:[{revision:2,saved_at:'2026-11-12T13:00:00Z',reason:'Adjusted the run',changed_change_ids:['c2'],changed_fields:['rationale']}]}
  failure=null;fireEvent.click(screen.getByRole('button',{name:'Reload proposal'}))
  await waitFor(()=>expect(screen.getAllByText(/Revision 2/).length).toBeGreaterThan(0))
  expect(screen.getByLabelText('Accept change c1')).not.toBeChecked()
  expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled()
  expect(screen.getByText('Revision history').closest('details')).not.toHaveAttribute('open')
  expect(screen.getByLabelText('Accept change c2').closest('tr')).toHaveClass('proposal-revised-row')
  await select('c2');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await waitFor(()=>expect(writes).toHaveLength(2))
  expect(writes[1].expected_revision).toBe(2)
  expect(writes[1].idempotency_key).not.toBe(writes[0].idempotency_key)
})
it('keeps a revision conflict blocked when reload fails',async()=>{
  failure='revision';mount();await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText(/edited while you reviewed it/)
  failReload=true;fireEvent.click(screen.getByRole('button',{name:'Reload proposal'}))
  await screen.findByText(/Refresh failed/)
  expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled()
  expect(screen.getByRole('button',{name:'Reload proposal'})).toBeEnabled()
  expect(writes).toHaveLength(1)
})
it('clears stale decision state when a newer current revision arrives',async()=>{
  failure='stale';mount();await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText(/This proposal is stale/)
  proposal={...proposal,revision:2,is_current:true,revisions:[{revision:2,saved_at:'2026-11-12T13:00:00Z',reason:'Updated recovery',changed_change_ids:['removed-c4'],changed_fields:['summary']}]}
  await clients[0].invalidateQueries({queryKey:['v2','proposals','p1']})
  await waitFor(()=>expect(screen.queryByText(/This proposal is stale/)).not.toBeInTheDocument())
  expect(screen.getByLabelText('Accept change c1')).not.toBeChecked()
  fireEvent.click(screen.getByText('Revision history'))
  expect(screen.getByText(/removed sessions: 1/)).toBeInTheDocument()
  failure=null;await select('c2');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await waitFor(()=>expect(writes).toHaveLength(2))
  expect(writes[1].expected_revision).toBe(2)
})
it('resets review selections when a background refresh reveals a new revision',async()=>{
  mount();await select('c1')
  proposal={...proposal,revision:2,revisions:[{revision:2,saved_at:'2026-11-12T13:00:00Z',reason:'Updated recovery',changed_change_ids:[],changed_fields:['summary']}]}
  await clients[0].invalidateQueries({queryKey:['v2','proposals','p1']})
  await waitFor(()=>expect(screen.getByLabelText('Accept change c1')).not.toBeChecked())
  expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled()
  await select('c3');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await waitFor(()=>expect(writes).toHaveLength(1))
  expect(writes[0].expected_revision).toBe(2)
})
it('rejects every item without claiming a calendar update',async()=>{
  mount();fireEvent.click(await screen.findByRole('button',{name:'Reject all'}))
  await screen.findByText('Decision recorded — calendar unchanged');expect(writes[0].reject_change_ids).toEqual(['c1','c2','c3']);expect(writes[0].accept_change_ids).toEqual([])
})
it('records explicit empty acknowledgment with no ambiguous rejection',async()=>{
  proposal.changes=[];mount();fireEvent.click(await screen.findByRole('button',{name:'Accept (no changes)'}))
  await screen.findByText('Decision recorded — calendar unchanged');expect(writes[0].accept_change_ids).toEqual([])
  expect(screen.queryByRole('button',{name:'Reject all'})).not.toBeInTheDocument()
})
it('requires calendar authority',async()=>{
  authority='legacy';mount();await screen.findByText('Planning upgrade required')
  expect(screen.getByLabelText('Accept change c1')).toBeDisabled();expect(writes).toHaveLength(0)
})
it('keeps imported prose visible without inventing structured reps',async()=>{
  proposal.changes[0].before={intent:'Imported easy prescription',notes:'Walk breaks as needed',legacy_unstructured:true,structure:null}
  mount();expect((await screen.findAllByText('Walk breaks as needed')).length).toBeGreaterThan(0);expect(screen.getAllByText(/Imported prescription/).length).toBeGreaterThan(0)
})
it('keeps malformed saved workouts reviewable and blocks accepting them',async()=>{
  const bad:PlannedStep={type:'work',duration_type:'time',duration_value:180,
    target:{modality:'effort',low:6,high:7,effort_cue:'Controlled'}}
  proposal.changes[0].after={intent:'Controlled intervals',notes:'Keep the run days',
    structure:[{type:'repeat',count:5,steps:[bad]}]}
  proposal.changes[1].before={structure:[bad]}
  mount()
  await screen.findByText('Controlled intervals')
  expect(screen.getAllByText(/This workout's steps are invalid/).length).toBeGreaterThanOrEqual(2)
  expect(screen.getByText('Keep the run days')).toBeInTheDocument()
  expect(screen.getByLabelText('Accept change c1')).toBeDisabled()
  expect(screen.getByLabelText('Accept change c2')).toBeEnabled()
  expect(screen.getByRole('button',{name:'Reject all'})).toBeEnabled()
  expect(writes).toHaveLength(0)
  await select('c2')
  fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await waitFor(()=>expect(writes).toHaveLength(1))
  expect(writes[0].accept_change_ids).toEqual(['c2'])
  expect(writes[0].reject_change_ids).toEqual(['c1','c3'])
})
it('renders repeated effort targets with RPE in the cue',async()=>{
  const work:PlannedStep={type:'work',duration_type:'time',duration_value:180,
    target:{modality:'effort',low:null,high:null,effort_cue:'RPE 6-7, controlled'}}
  proposal.changes[0].after={structure:[{type:'repeat',count:5,steps:[work]}]}
  mount()
  expect(await screen.findByText('5 × (Work 3:00 · RPE 6-7, controlled)')).toBeInTheDocument()
  expect(screen.getByLabelText('Accept change c1')).toBeEnabled()
  expect(writes).toHaveLength(0)
})
it('requires separate selections for block and anchor changes',async()=>{
  proposal.changes=[]
  proposal.block_change={decision:'start',block_uid:null,version_fields:{objective:'Build consistency',constraints:[{kind:'schedule',text:'Keep strength days'}]}}
  proposal.anchor_changes=[{anchor_key:'hr_threshold_lower-2026-11-12',kind:'hr_threshold_lower',value_low:165,value_high:null,unit:'bpm',protocol:'manual',confidence:'moderate',calibrated_at:'2026-11-12T12:00:00Z',supersedes_key:null}]
  mount();expect(await screen.findByLabelText('Accept block change')).not.toBeChecked()
  expect(screen.getByLabelText('Accept anchor hr_threshold_lower-2026-11-12')).not.toBeChecked()
  fireEvent.click(screen.getByLabelText('Accept block change'));fireEvent.click(screen.getByLabelText('Accept anchor hr_threshold_lower-2026-11-12'))
  fireEvent.click(screen.getByRole('button',{name:'Accept selected'}));await waitFor(()=>expect(writes).toHaveLength(1))
  expect(writes[0].accept_block_change).toBe(true);expect(writes[0].accept_anchor_changes).toEqual(['hr_threshold_lower-2026-11-12'])
})
it('shows saved block and anchor decisions after reopening a terminal proposal',async()=>{
  proposal.status='partially_accepted';proposal.is_current=false;proposal.changes=[]
  proposal.block_change={decision:'continue',block_uid:'b1',version_fields:{objective:'Continue'}}
  proposal.anchor_changes=[{anchor_key:'hr_threshold_lower-2026-11-12',kind:'hr_threshold_lower',value_low:165,value_high:null,unit:'bpm',protocol:'manual',confidence:'moderate',calibrated_at:'2026-11-12T12:00:00Z',supersedes_key:null}]
  proposal.decision_result={proposal_id:'p1',status:'partially_accepted',calendar_version:null,block_version_id:'v1',anchor_keys:[],stale_proposals:[]}
  mount();await screen.findByText('Block decision: accepted');expect(screen.getByText('Anchor decision: rejected')).toBeInTheDocument()
  expect(screen.queryByLabelText('Accept block change')).not.toBeInTheDocument()
  expect(screen.getByText('Decision recorded — calendar unchanged')).toBeInTheDocument()
})


it('shows the complete proposed workouts in date order with matching numbered reasons and no evidence tags',async()=>{
  proposal.rationale='Keep the training manageable. [E-AER-01, P001]'
  proposal.changes=[
    {change_id:'c1',op:'modify',session_uid:'s1',before:{local_date:'2026-11-16',kind:'run',recipe_id:'REC001',intent:'Conversational effort',planned_duration_s:1800,planned_distance_m:5000,notes:'Keep the route flat'},after:{planned_duration_s:2100},current:null,reason:'Add five easy minutes. [P001]',decision:'pending',material_flags:[]},
    {change_id:'c2',op:'add',session_uid:null,before:null,after:{local_date:'2026-11-12',kind:'strength',intent:'Full body A',planned_duration_s:3600},current:null,reason:'Preserve the lifting commitment.',decision:'pending',material_flags:[]},
    {change_id:'c3',op:'delete',session_uid:'s3',before:{local_date:'2026-11-14',kind:'run',recipe_id:'REC002',intent:'Long easy run',planned_duration_s:4500},after:null,current:null,reason:'Allow more recovery. [E-AER-01]',decision:'pending',material_flags:[]},
  ]
  mount()
  const table=await screen.findByRole('table',{name:'Proposed plan changes'})
  const rows=within(table).getAllByRole('row').slice(1)
  expect(rows).toHaveLength(3)
  expect(within(rows[0]).getByText('Full body A')).toBeInTheDocument()
  expect(within(rows[1]).getByText('Remove this session from the plan.')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Conversational effort')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Duration: 35m')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Distance: 5.00 km')).toBeInTheDocument()
  expect(within(rows[2]).getByText('Keep the route flat')).toBeInTheDocument()
  expect(within(rows[2]).getByRole('link',{name:'Read reason 3'})).toHaveAttribute('href','#proposal-reason-3')
  const reasons=screen.getByText('Session reasons and comparisons').parentElement!
  const items=within(reasons).getAllByRole('listitem')
  expect(items.map(item=>item.querySelector('p')?.textContent)).toEqual(['Preserve the lifting commitment.','Allow more recovery.','Add five easy minutes.'])
  expect(screen.queryByText(/E-AER-01|P001|REC001|REC002|Evidence and policies/)).not.toBeInTheDocument()
  await select('c1');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await waitFor(()=>expect(writes).toHaveLength(1))
  expect(writes[0]).toMatchObject({accept_change_ids:['c1'],reject_change_ids:['c2','c3']})
})

it('shows moved dates and preserves explicit cleared values in the proposal',async()=>{
  proposal.changes=[{...proposal.changes[0],op:'move',before:{local_date:'2026-11-12',kind:'run',planned_distance_m:5000,notes:'Old note'},after:{local_date:'2026-11-13',planned_distance_m:null,notes:null}}]
  mount()
  const table=await screen.findByRole('table',{name:'Proposed plan changes'})
  expect(within(table).getByText(/Previously Thu, Nov 12/)).toBeInTheDocument()
  expect(within(table).getByText('Distance: Not specified')).toBeInTheDocument()
  expect(within(table).queryByText('Old note')).not.toBeInTheDocument()
})

it('confirms discard at the reviewed revision without making a decision',async()=>{
  proposal.revision=3;mount()
  fireEvent.click(await screen.findByRole('button',{name:'Discard proposal'}))
  expect(screen.getByText(/removed from the open list/)).toBeInTheDocument()
  expect(deletes).toEqual([])
  fireEvent.click(screen.getByRole('button',{name:'Confirm discard'}))
  await screen.findByText(/Proposal discarded/)
  expect(deletes).toEqual([3]);expect(writes).toEqual([])
  expect(screen.queryByRole('button',{name:'Reject all'})).not.toBeInTheDocument()
  expect(screen.queryByText('Decision: rejected')).not.toBeInTheDocument()
  expect(screen.getByRole('link',{name:'Return home'})).toHaveAttribute('href','#home')
})
it('cancels discard without a write',async()=>{
  mount();fireEvent.click(await screen.findByRole('button',{name:'Discard proposal'}))
  fireEvent.click(screen.getByRole('button',{name:'Cancel'}))
  expect(screen.queryByRole('button',{name:'Confirm discard'})).not.toBeInTheDocument()
  expect(deletes).toEqual([]);expect(writes).toEqual([])
})
it.each(['stale','invalid'] as const)('can discard a %s proposal',async status=>{
  proposal.status=status;proposal.is_current=false;mount()
  fireEvent.click(await screen.findByRole('button',{name:'Discard proposal'}))
  fireEvent.click(screen.getByRole('button',{name:'Confirm discard'}))
  await screen.findByText(/Proposal discarded/)
  expect(deletes).toEqual([1])
})
it('clears a mutation stale warning after discard',async()=>{
  failure='stale';mount();await select('c1')
  fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText(/This proposal is stale/)
  fireEvent.click(screen.getByRole('button',{name:'Discard proposal'}))
  fireEvent.click(screen.getByRole('button',{name:'Confirm discard'}))
  await screen.findByText(/Proposal discarded/)
  expect(screen.queryByText(/This proposal is stale/)).not.toBeInTheDocument()
  expect(screen.queryByText(/unchecked changes will be rejected/)).not.toBeInTheDocument()
})
it('blocks discard after a revision conflict until an explicit reload',async()=>{
  failure='revision';mount();fireEvent.click(await screen.findByRole('button',{name:'Discard proposal'}))
  fireEvent.click(screen.getByRole('button',{name:'Confirm discard'}))
  await screen.findByText(/edited while you reviewed it/)
  expect(screen.getByRole('button',{name:'Confirm discard'})).toBeDisabled()
  expect(deletes).toEqual([1])
  proposal={...proposal,revision:2};failure=null
  fireEvent.click(screen.getByRole('button',{name:'Reload proposal'}))
  await waitFor(()=>expect(screen.getByRole('button',{name:'Discard proposal'})).toBeEnabled())
  fireEvent.click(screen.getByRole('button',{name:'Discard proposal'}))
  fireEvent.click(screen.getByRole('button',{name:'Confirm discard'}))
  await waitFor(()=>expect(deletes).toEqual([1,2]))
})
it.each(['accepted','rejected','discarded'] as const)('hides discard for %s proposals',async status=>{
  proposal.status=status;mount();await screen.findByText(/Adjust the next week/)
  expect(screen.queryByRole('button',{name:'Discard proposal'})).not.toBeInTheDocument()
})
