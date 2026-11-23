import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import {
  CoachText,
  EffortLabel,
  INDICATOR_LABELS,
  LegacyText,
  RuleList,
  SourceChips,
  WhyList,
} from '../src/components/CoachText'

afterEach(cleanup)

it('renders paragraphs and bullets as stored without interpreting markup', () => {
  const { container } = render(<CoachText text={'First line\n\n- one\n- two\n\n<b>x</b>'} />)
  expect(screen.getByText('First line').tagName).toBe('P')
  expect(screen.getAllByRole('listitem').map((item) => item.textContent)).toEqual(['one', 'two'])
  expect(screen.getByText('<b>x</b>')).toBeVisible()
  expect(container.querySelector('b')).toBeNull()
})

it('labels observations, research, inference and athlete priorities', () => {
  render(
    <WhyList
      items={[
        { kind: 'observation', text: 'Last week went to plan' },
        { kind: 'research', text: 'Progress in small increments' },
        { kind: 'inference', text: 'The next step can fit' },
        { kind: 'priority', text: 'Keep Thursday easy' },
      ]}
    />,
  )
  const rows = screen.getAllByRole('listitem')
  expect(rows[0]).toHaveTextContent('ObservedLast week went to plan')
  expect(rows[1]).toHaveTextContent('ResearchProgress in small increments')
  expect(rows[2]).toHaveTextContent('InferenceThe next step can fit')
  expect(rows[3]).toHaveTextContent('Your priorityKeep Thursday easy')
})

it('shows an adjust-if rule with its condition and action', () => {
  render(
    <RuleList label="Adjust if" rules={[{ when: 'Rep pace fades', then: 'stop after rep 4' }]} />,
  )
  expect(screen.getByRole('heading', { name: 'Adjust if' })).toBeVisible()
  expect(screen.getByRole('listitem')).toHaveTextContent('Rep pace fades → stop after rep 4')
})

it('shows a range or a single RPE number with feel', () => {
  const { rerender } = render(
    <EffortLabel effort={{ rpe_low: 6, rpe_high: 7, feel: 'controlled' }} />,
  )
  expect(screen.getByText('RPE 6–7')).toBeVisible()
  expect(screen.getByText('controlled')).toBeVisible()
  rerender(<EffortLabel effort={{ rpe_low: 3, rpe_high: 3, feel: 'easy' }} />)
  expect(screen.getByText('RPE 3')).toBeVisible()
})

it('counts sources and shows publications in source titles', () => {
  render(
    <SourceChips
      sources={[
        {
          kind: 'evidence',
          title: 'Threshold sessions',
          papers: ['Paper A (2020)', 'Paper B (2021)'],
        },
        { kind: 'policy', title: 'Make one change', papers: [] },
      ]}
    />,
  )
  const summary = screen.getByText('Sources (2)')
  const disclosure = summary.closest('details')!
  expect(disclosure).not.toHaveAttribute('open')
  fireEvent.click(summary)
  const chips = within(disclosure)
  expect(chips.getByText('Threshold sessions')).toHaveAttribute(
    'title',
    'Paper A (2020); Paper B (2021)',
  )
  expect(chips.getByText('Make one change')).not.toHaveAttribute('title')
})

it('shows earlier text in a closed disclosure', () => {
  render(<LegacyText text="Saved explanation" />)
  const summary = screen.getByText('Earlier format')
  expect(summary.closest('details')).not.toHaveAttribute('open')
  expect(screen.getByText('Saved explanation')).not.toBeVisible()
  fireEvent.click(summary)
  expect(screen.getByText('Saved explanation')).toBeVisible()
})

it('omits empty why, rules, sources and earlier-format controls', () => {
  const { container } = render(
    <>
      <WhyList items={[]} />
      <RuleList label="Adjust if" rules={[]} />
      <SourceChips sources={[]} />
      <LegacyText text={null} />
    </>,
  )
  expect(container).toBeEmptyDOMElement()
})

it('provides display labels for all supported indicators', () => {
  expect(INDICATOR_LABELS).toEqual({
    quality_progression: 'Workout progression',
    aerobic_efficiency: 'Aerobic efficiency',
    key_sessions: 'Key sessions',
    rpe_vs_intent: 'Effort vs plan',
    other: 'Other',
  })
})
