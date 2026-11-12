import { useQuery } from '@tanstack/react-query'
import { api, dateLabel, qk, RECIPE_LABELS, type BlockVersion, type CalendarView } from '../api'
import { QueryState } from '../components/QueryState'

export function Block() {
  const active = useQuery({queryKey:qk.blocksActive,queryFn:()=>api<BlockVersion|null>('/blocks/active')})
  const calendar = useQuery({queryKey:qk.calendarView('head'),queryFn:()=>api<CalendarView>('/calendar')})
  const block = active.data?.data
  const history = useQuery({queryKey:['v2','blocks','history',block?.block_uid],enabled:!!block,
    queryFn:()=>api<{items:BlockVersion[]}>(`/blocks/${encodeURIComponent(block!.block_uid)}/history`)})
  const days = (a:string,b:string)=>Math.floor((Date.parse(`${a}T12:00:00Z`)-Date.parse(`${b}T12:00:00Z`))/86400000)
  const today = calendar.data?.data.today
  return <section className="page-content"><div className="page-heading"><div><span className="eyebrow">TRAINING DIRECTION</span><h1>Training block</h1></div><a href="#calendar">Calendar</a></div>
    <QueryState loading={active.isPending} error={active.error} retry={()=>{void active.refetch()}}>
      {block===null && <div className="panel"><h2>No active training block</h2><p>Ask the coach for a block review to choose the next training objective.</p></div>}
      {block && <>
        <div className="panel"><h2>{block.objective}</h2><p>{block.rationale}</p><p>{block.status} · {block.objective_status.replaceAll('_',' ')}</p>
          {today && <p>Week {Math.max(1,Math.floor(days(today,block.start_date)/7)+1)} of {Math.max(1,Math.ceil(days(block.review_date,block.start_date)/7))}</p>}
          <p>{dateLabel(block.start_date)} · Review {dateLabel(block.review_date)}</p>
          <h3>Maintained qualities</h3><p>{block.maintained_qualities.join(', ') || 'Not specified'}</p>
          <h3>Eligible sessions</h3><p>{block.eligible_recipe_ids.map(id=>RECIPE_LABELS[id] || id).join(', ') || 'Not specified'}</p>
          <h3>Progression</h3><p>{block.progression_dimension.replaceAll('_',' ')}</p>
          {block.constraints.length>0 && <><h3>Constraints</h3><ul>{block.constraints.map((constraint,index)=><li key={index}>{constraint.text}</li>)}</ul></>}
          {block.non_goals.length>0 && <><h3>Outside this block's focus</h3><ul>{block.non_goals.map(value=><li key={value}>{value}</li>)}</ul></>}
          <h3>Completion indicators</h3><ul>{block.completion_indicators.map(value=><li key={value}>{value}</li>)}</ul>
          <h3>Earlier review triggers</h3><ul>{block.early_review_triggers.map(value=><li key={value}>{value}</li>)}</ul>
        </div>
        <div className="panel"><h2>Block history</h2><QueryState loading={history.isPending} error={history.error} retry={()=>{void history.refetch()}}>
          {history.data?.data.items.map(version=><article className="block-history" key={version.id}><h3>Version {version.version} · {version.status}</h3><p>{version.objective}</p><p>{version.rationale}</p>
            {version.proposal_id && <a href={`#proposal/${encodeURIComponent(version.proposal_id)}`}>View reviewed proposal</a>}</article>)}
        </QueryState></div>
      </>}
    </QueryState>
  </section>
}
