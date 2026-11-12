import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

/** Native details: retains summary, open and onToggle semantics. */
export function Disclosure({
  className,
  variant = 'plain',
  ...props
}: ComponentProps<'details'> & { variant?: 'plain' | 'card' }) {
  return (
    <details
      data-slot="disclosure"
      className={cn(
        'group [&>summary]:cursor-pointer [&>summary]:font-medium [&>summary]:focus-visible:outline-ring',
        variant === 'card' && 'rounded-xl border bg-card p-5 text-card-foreground shadow-sm',
        className,
      )}
      {...props}
    />
  )
}
