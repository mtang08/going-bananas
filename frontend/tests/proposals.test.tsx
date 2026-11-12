import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ProposalReview } from '../src/pages/ProposalReview'
import type { ProposalDecision, ProposalDetail } from '../src/api/types/coach'

let proposal:ProposalDetail
let authority='calendar'
let failure:'network'|'subset'|'stale'|null=null
let writes:ProposalDecision[]=[]
const clients:QueryClient[]=[]
beforeEach(()=>{
  authority='calendar';failure=null;writes=[]
  proposal={id:'p1',operation:'review_rolling_plan',status:'pending',submitted_at:'2026-11-12T12:00:00Z',decided_at:null,
    summary:'Adjust the next week',rationale:'Keep the run manageable',confidence:{decision:'moderate',evidence:'high',data:'moderate'},
    base_calendar_version:7,base_block_version_id:null,snapshot_id:'snapshot',head:7,is_current:true,
    evidence_ids:['E-AER-01'],policy_ids:['P001'],recipe_ids:['REC001'],follow_up:'Review after the run',escalation:null,
    block_change:null,anchor_changes:[],validation_errors:[],skill_version:'running-coach.v1',
    changes:['c1','c2','c3'].map((id,index)=>({change_id:id,op:'modify',session_uid:`s${index}`,
      before:{intent:'Easy',planned_duration_s:1800,structure:null},after:{planned_duration_s:2100},current:{intent:'Easy'},
      reason:`Adjustment ${index+1}`,decision:'pending',material_flags:[]}))}
  vi.stubGlobal('fetch',vi.fn(async(input:string,options?:RequestInit)=>{
    const url=String(input)
    if(options?.method==='POST'){
      const body=JSON.parse(String(options.body)) as ProposalDecision;writes.push(body)
      if(failure==='network')throw new Error('offline')
      if(failure)return {ok:false,status:failure==='stale'?409:422,json:async()=>({error:{code:failure==='stale'?'stale_evidence':'proposal_invalid_subset',message:'Review the selected changes',fields:[{path:'changes.1',message:'Preserve strength count'}]}})}
      const status=body.accept_change_ids.length===0&&proposal.changes.length?'rejected':body.reject_change_ids.length?'partially_accepted':'accepted'
      proposal={...proposal,status,is_current:false,changes:proposal.changes.map(change=>({...change,decision:body.accept_change_ids.includes(change.change_id)?'accepted':'rejected'}))}
      return {ok:true,json:async()=>({schema_version:'v1',mode:'demo',data_revision:2,data:{proposal_id:'p1',status,calendar_version:body.accept_change_ids.length?8:null,block_version_id:null,anchor_keys:[],stale_proposals:[]}})}
    }
    return {ok:true,json:async()=>({schema_version:'v1',mode:'demo',data_revision:1,data:url.endsWith('/profile')?{planning_authority:authority}:proposal})}
  }))
})
afterEach(()=>{cleanup();clients.forEach(client=>client.clear());clients.length=0;vi.unstubAllGlobals()})
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});clients.push(client);return render(<QueryClientProvider client={client}><ProposalReview proposalId="p1"/></QueryClientProvider>)}
async function select(...ids:string[]){for(const id of ids)fireEvent.click(await screen.findByLabelText(`Accept change ${id}`))}

it('requires individual review and submits complete partial selection',async()=>{
  mount();expect(await screen.findByLabelText('Accept change c1')).not.toBeChecked();expect(writes).toHaveLength(0)
  expect(screen.getByRole('button',{name:'Accept selected'})).toBeDisabled()
  await select('c1','c3');fireEvent.click(screen.getByRole('button',{name:'Accept selected'}))
  await screen.findByText('Accepted — calendar version 8')
  expect(writes[0]).toEqual({idempotency_key:expect.any(String),expected_head:7,accept_change_ids:['c1','c3'],reject_change_ids:['c2'],accept_block_change:false,accept_anchor_changes:[]})
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
  mount();await screen.findByText('Walk breaks as needed');expect(screen.getByText(/Imported prescription/)).toBeInTheDocument()
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
