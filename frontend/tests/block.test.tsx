import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Block } from '../src/pages/Block'
import type { BlockVersion } from '../src/api'
let block:BlockVersion|null
const clients:QueryClient[]=[]
beforeEach(()=>{
  block={id:'v1',block_uid:'b1',version:1,status:'active',objective:'Build consistency',rationale:'Keep the week repeatable',
    maintained_qualities:['Easy endurance'],non_goals:['Peak racing'],eligible_recipe_ids:['REC001'],progression_dimension:'duration',
    constraints:[{kind:'schedule',text:'Keep strength days'}],start_date:'2026-11-01',review_date:'2026-12-13',
    completion_indicators:['Tolerated weeks'],early_review_triggers:['Symptoms increase'],objective_status:'unresolved',created_at:'2026-11-01T12:00:00Z',proposal_id:'p1'}
  vi.stubGlobal('fetch',vi.fn(async(input:string)=>({ok:true,json:async()=>({schema_version:'v1',mode:'demo',data_revision:1,
    data:String(input).endsWith('/calendar')?{today:'2026-11-12'}:String(input).endsWith('/history')?{items:block?[block]:[]}:block})})))
})
afterEach(()=>{cleanup();clients.forEach(client=>client.clear());clients.length=0;vi.unstubAllGlobals()})
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client);render(<QueryClientProvider client={client}><Block/></QueryClientProvider>)}
it('shows no active block without offering automatic changes',async()=>{
  block=null;mount();await screen.findByText('No active training block');expect(screen.queryByRole('button',{name:/Create/})).not.toBeInTheDocument()
})
it('shows objective, athlete-local week, constraints and lineage',async()=>{
  mount();await screen.findByText('11 days elapsed');expect(screen.getByRole('heading',{name:'Build consistency'})).toBeInTheDocument()
  expect(screen.getByText('Keep strength days')).toBeInTheDocument();expect(await screen.findByRole('link',{name:'View reviewed proposal'})).toHaveAttribute('href','#proposal/p1')
  expect(screen.getByText('Symptoms increase')).toBeInTheDocument()
})

it('shows an overdue review without claiming objective completion',async()=>{
  block!.review_date='2026-11-10';mount();await screen.findByText('Review overdue · 2 days');
  expect(screen.getByText('Review criteria; achievement has not been verified here.')).toBeInTheDocument();
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
})
it('links the empty state to the review guide',async()=>{
  block=null;mount();expect(await screen.findByRole('link',{name:'How to review with the coach'})).toHaveAttribute('href','#guide')
})

it('labels review due today without a completion percentage',async()=>{
  block!.review_date='2026-11-12';mount();await screen.findByText('Review due today');
  expect(screen.getByRole('list',{name:'Block elapsed time'})).toBeInTheDocument()
})
