import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { Guide } from '../src/pages/Guide'
import guide from 'virtual:user-guide'
import { BENCHMARK_PROMPT, BLOCK_PROMPT, EXCEPTION_PROMPT, REASSESS_PROMPT, WEEKLY_PROMPT, racePrompt } from '../src/coachPrompts'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('provides the Sunday workflow with a copyable prompt and downloadable guide', async () => {
  const writeText = vi.fn().mockResolvedValue(undefined)
  const original = Object.getOwnPropertyDescriptor(navigator, 'clipboard')
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } })
  try {
    render(<Guide />)
    expect(screen.getByRole('heading', { name: 'User guide' })).toBeInTheDocument()
    const topic = screen.getByRole('heading', { name: 'Sunday review', hidden: true }).closest('details')!
    fireEvent.click(topic.querySelector('summary')!)
    fireEvent.click(within(topic).getByRole('button', { name: 'Copy prompt' }))
    await waitFor(() => expect(writeText).toHaveBeenCalledWith(expect.stringContaining('$going-bananas-coach for my Sunday review')))
    expect(within(topic).getByRole('status')).toHaveTextContent('Copied')
    const download = screen.getByRole('link', { name: 'Download guide' })
    expect(download).toHaveAttribute('download', 'going-bananas-user-guide.md')
    expect(decodeURIComponent(download.getAttribute('href')!)).toContain('Training blocks and weekly plans')
  } finally {
    if (original) Object.defineProperty(navigator, 'clipboard', original)
    else Reflect.deleteProperty(navigator, 'clipboard')
  }
})

it('opens a chosen topic without changing the app route', () => {
  const original = Element.prototype.scrollIntoView
  Element.prototype.scrollIntoView = vi.fn()
  try {
    window.location.hash = '#guide'
    render(<Guide />)
    fireEvent.click(screen.getByRole('button', { name: 'Training blocks and weekly plans' }))
    const heading = screen.getByRole('heading', { name: 'Training blocks and weekly plans' })
    expect(heading.closest('details')).toHaveAttribute('open')
    expect(window.location.hash).toBe('#guide')
    expect(document.activeElement).toBe(heading.closest('summary'))
  } finally { Element.prototype.scrollIntoView = original }
})


it('repeats every coach prompt and drops removed pages', () => {
  for (const prompt of [WEEKLY_PROMPT, EXCEPTION_PROMPT, BLOCK_PROMPT, BENCHMARK_PROMPT, REASSESS_PROMPT, racePrompt('…', '…')])
    expect(guide.includes('> ' + prompt)).toBe(true)
  for (const heading of ['## Exception review', '## After a race', '## Block-ending benchmark'])
    expect(guide).toContain(heading)
  for (const removed of ['(#history)', '(#strength)', '(#coach)', 'Data & settings'])
    expect(guide).not.toContain(removed)
})
