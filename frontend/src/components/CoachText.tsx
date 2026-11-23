import type { Effort } from '../api/types/calendar'
import type { IndicatorSource } from '../api/types/blocks'
import type { CitedSource, Rule, Why, WhyKind } from '../api/types/coachText'
import { Badge, Disclosure } from './ui'
import './coach-text.css'

export const INDICATOR_LABELS: Record<IndicatorSource, string> = {
  quality_progression: 'Workout progression',
  aerobic_efficiency: 'Aerobic efficiency',
  key_sessions: 'Key sessions',
  rpe_vs_intent: 'Effort vs plan',
  other: 'Other',
}

const WHY_LABELS: Record<WhyKind, string> = {
  observation: 'Observed',
  research: 'Research',
  inference: 'Inference',
  priority: 'Your priority',
}

export function CoachText({ text }: { text: string }) {
  return (
    <div className="proposal-copy">
      {text
        .split(/\n\s*\n/)
        .filter((part) => part.trim())
        .map((part, index) => {
          const lines = part.trim().split('\n')
          return lines.every((line) => /^\s*[-*] /.test(line)) ? (
            <ul key={index}>
              {lines.map((line, i) => (
                <li key={i}>{line.replace(/^\s*[-*] /, '')}</li>
              ))}
            </ul>
          ) : (
            <p key={index}>{part}</p>
          )
        })}
    </div>
  )
}

export function WhyList({ items }: { items: Why[] }) {
  if (!items.length) return null
  return (
    <ul className="coach-why">
      {items.map((item, index) => (
        <li key={index}>
          <Badge variant="secondary">{WHY_LABELS[item.kind]}</Badge>
          <span>{item.text}</span>
        </li>
      ))}
    </ul>
  )
}

export function RuleList({ label, rules }: { label: string; rules: Rule[] }) {
  if (!rules.length) return null
  return (
    <div className="coach-rules">
      <h4>{label}</h4>
      <ul>
        {rules.map((rule, index) => (
          <li key={index}>
            <span>{rule.when}</span> → <span>{rule.then}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function EffortLabel({ effort }: { effort: Effort }) {
  const range =
    effort.rpe_low === effort.rpe_high
      ? `${effort.rpe_low}`
      : `${effort.rpe_low}–${effort.rpe_high}`
  return (
    <span className="coach-effort">
      <Badge variant="outline">RPE {range}</Badge>
      <span>{effort.feel}</span>
    </span>
  )
}

export function SourceChips({ sources }: { sources: CitedSource[] }) {
  if (!sources.length) return null
  return (
    <Disclosure className="coach-sources">
      <summary>Sources ({sources.length})</summary>
      <div className="coach-source-chips">
        {sources.map((source) => (
          <Badge
            key={`${source.kind}:${source.title}`}
            variant="outline"
            className="h-auto whitespace-normal text-left"
            title={source.papers.length ? source.papers.join('; ') : undefined}
          >
            {source.title}
          </Badge>
        ))}
      </div>
    </Disclosure>
  )
}

export function LegacyText({ text }: { text: string | null }) {
  if (!text) return null
  return (
    <Disclosure className="coach-legacy">
      <summary>Earlier format</summary>
      <CoachText text={text} />
    </Disclosure>
  )
}
