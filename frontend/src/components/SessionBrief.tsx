import type { ReactNode } from 'react'
import type { SessionBrief as SessionBriefData } from '../api/types/calendar'
import { CoachText, EffortLabel, RuleList } from './CoachText'
import { Disclosure } from './ui'

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="session-brief-field">
      <h4>{label}</h4>
      {children}
    </div>
  )
}

export function SessionBrief({
  brief,
  notes,
  layout,
}: {
  brief: SessionBriefData | null
  notes: string | null
  layout: 'today' | 'full' | 'check'
}) {
  if (layout === 'check') {
    if (!brief) return null
    return (
      <div className="session-brief">
        <EffortLabel effort={brief.effort} />
        <RuleList label="Adjust if" rules={brief.adjust_if} />
      </div>
    )
  }
  const note = notes?.trim() ?? ''
  if (!brief && !note) return null
  const focus = brief?.focus ?? []
  const focusField = focus.length ? (
    <Field label="Focus">
      <ul>
        {focus.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </Field>
  ) : null
  const whyField = brief?.why ? (
    <Field label="Why">
      <CoachText text={brief.why} />
    </Field>
  ) : null
  const notesField = note ? (
    <Field label="Notes">
      <p className="plan-session-notes">{note}</p>
    </Field>
  ) : null
  const adjustIf = <RuleList label="Adjust if" rules={brief?.adjust_if ?? []} />
  if (layout === 'full') {
    return (
      <div className="session-brief">
        {focusField}
        {adjustIf}
        {whyField}
        {notesField}
      </div>
    )
  }
  return (
    <div className="session-brief">
      {adjustIf}
      {(focusField || whyField || notesField) && (
        <Disclosure className="session-brief-more">
          <summary>Why and notes</summary>
          {focusField}
          {whyField}
          {notesField}
        </Disclosure>
      )}
    </div>
  )
}
