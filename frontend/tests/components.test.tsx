import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { Modal } from '../src/components/Modal'

afterEach(cleanup)

it('Modal uses a labelled dialog and closes from the close button and Escape', async () => {
  const close = vi.fn()
  render(
    <Modal label="Demo" close={close}>
      <p>Body</p>
    </Modal>,
  )
  const dialog = screen.getByRole('dialog', { name: 'Demo' })
  fireEvent.mouseDown(dialog)
  expect(close).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(close).toHaveBeenCalledTimes(1)
  fireEvent.keyDown(dialog, { key: 'Escape' })
  expect(close).toHaveBeenCalledTimes(2)
})

it('Modal adds caller classes and connects an optional description', () => {
  render(
    <Modal
      label="Demo"
      description="What this dialog does"
      className="detail-modal"
      close={vi.fn()}
    >
      <p>Body</p>
    </Modal>,
  )
  const dialog = screen.getByRole('dialog', { name: 'Demo' })
  expect(dialog).toHaveClass('modal', 'detail-modal')
  expect(dialog).toHaveAccessibleDescription('What this dialog does')
})

it('Modal traps keyboard focus and restores focus to its opener when unmounted', async () => {
  function Example() {
    const [open, setOpen] = useState(false)
    return (
      <>
        <button onClick={() => setOpen(true)}>Open example</button>
        {open && (
          <Modal label="Example" close={() => setOpen(false)}>
            <button>First action</button>
            <button>Last action</button>
          </Modal>
        )}
      </>
    )
  }
  render(<Example />)
  const opener = screen.getByRole('button', { name: 'Open example' })
  opener.focus()
  fireEvent.click(opener)
  const first = screen.getByRole('button', { name: 'First action' })
  const close = screen.getByRole('button', { name: 'Close' })
  await waitFor(() => expect(first).toHaveFocus())
  close.focus()
  fireEvent.keyDown(close, { key: 'Tab' })
  expect(first).toHaveFocus()
  fireEvent.keyDown(first, { key: 'Tab', shiftKey: true })
  expect(close).toHaveFocus()
  fireEvent.keyDown(close, { key: 'Escape' })
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  await waitFor(() => expect(opener).toHaveFocus())
})
