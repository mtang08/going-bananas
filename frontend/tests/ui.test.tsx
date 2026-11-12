import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Button, Card, Disclosure, Input, NativeSelect, Textarea } from '../src/components/ui'

afterEach(cleanup)

it('preserves native form values, select events, and implicit button submission', () => {
  const submit = vi.fn((event: React.FormEvent) => event.preventDefault())
  const select = vi.fn()
  render(
    <form onSubmit={submit}>
      <Input aria-label="Mileage" name="mileage" type="number" defaultValue={5} />
      <Input aria-label="Date" type="date" defaultValue="2026-11-12" />
      <Input aria-label="File" type="file" />
      <Textarea aria-label="Notes" defaultValue="Felt good" />
      <NativeSelect
        aria-label="Unit"
        name="unit"
        onChange={(event) => select(event.currentTarget.value)}
      >
        <option value="mi">Miles</option>
        <option value="km">Kilometers</option>
      </NativeSelect>
      <Button>Save</Button>
    </form>,
  )
  fireEvent.change(screen.getByLabelText('Unit'), { target: { value: 'km' } })
  expect(select).toHaveBeenCalledWith('km')
  expect(screen.getByLabelText('Mileage')).toHaveValue(5)
  expect(screen.getByLabelText('Date')).toHaveValue('2026-11-12')
  expect(screen.getByLabelText('File')).toHaveAttribute('type', 'file')
  fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  expect(submit).toHaveBeenCalledOnce()
})

it('supports composition, direct Card children, and caller utility overrides', () => {
  render(
    <Card className="p-2">
      <Button asChild variant="outline">
        <a href="#history">History</a>
      </Button>
    </Card>,
  )
  const link = screen.getByRole('link', { name: 'History' })
  expect(link).toHaveAttribute('href', '#history')
  expect(link.parentElement).toHaveClass('p-2')
  expect(link.parentElement).not.toHaveClass('p-5')
})

it('retains native details open and toggle semantics', () => {
  const toggle = vi.fn()
  render(
    <Disclosure open onToggle={toggle}>
      <summary>Evidence</summary>
      <p>Details</p>
    </Disclosure>,
  )
  const details = screen.getByText('Evidence').parentElement as HTMLDetailsElement
  expect(details.open).toBe(true)
  fireEvent(details, new Event('toggle'))
  expect(toggle).toHaveBeenCalledOnce()
})
