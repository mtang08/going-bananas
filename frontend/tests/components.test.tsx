import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Modal } from '../src/components/Modal'

afterEach(cleanup)

it('Modal renders a labelled dialog and closes from backdrop and button', () => {
  const close = vi.fn()
  render(<Modal label="Demo" close={close}><p>Body</p></Modal>)
  const dialog = screen.getByRole('dialog', { name: 'Demo' })
  expect(dialog.classList.contains('modal')).toBe(true)
  fireEvent.mouseDown(dialog)
  expect(close).toHaveBeenCalledTimes(0)
  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(close).toHaveBeenCalledTimes(1)
  fireEvent.mouseDown(dialog.parentElement!)
  expect(close).toHaveBeenCalledTimes(2)
})

it('Modal appends an extra class', () => {
  render(<Modal label="Demo" className="detail-modal" close={vi.fn()}><p>Body</p></Modal>)
  expect(Array.from(screen.getByRole('dialog', { name: 'Demo' }).classList)).toEqual(['modal', 'detail-modal'])
})
