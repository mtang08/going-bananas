import { useRef, type ReactNode } from 'react'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from './ui'
import { cn } from '../lib/utils'

/** Controlled Radix dialog; preserves the app's existing label/close interface. */
export function Modal({
  label,
  description,
  className,
  close,
  children,
}: {
  label: string
  description?: string
  className?: string
  close: () => void
  children: ReactNode
}) {
  // These callers mount the dialog conditionally rather than using DialogTrigger.
  const returnFocus = useRef(
    document.activeElement instanceof HTMLElement ? document.activeElement : null,
  )
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent
        className={cn('modal', className)}
        {...(!description ? { 'aria-describedby': undefined } : {})}
        onCloseAutoFocus={(event) => {
          event.preventDefault()
          returnFocus.current?.focus()
        }}
      >
        <DialogTitle className="sr-only">{label}</DialogTitle>
        {description && <DialogDescription>{description}</DialogDescription>}
        {children}
      </DialogContent>
    </Dialog>
  )
}
