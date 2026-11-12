import type { ReactNode } from 'react'
import { X } from 'lucide-react'
export function Modal({ label, className, close, children }: { label: string; className?: string; close: () => void; children: ReactNode }) {
  return <div className="modal-backdrop" onMouseDown={close}><div className={className ? `modal ${className}` : 'modal'} role="dialog" aria-modal="true" aria-label={label} onMouseDown={e => e.stopPropagation()}><button className="icon-button close" aria-label="Close" onClick={close}><X/></button>{children}</div></div>
}
