import { CircleHelp } from 'lucide-react'

export function Empty({ title, text }: { title: string; text: string }) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed bg-muted/40 px-6 py-10 text-center">
      <CircleHelp size={23} className="text-muted-foreground" aria-hidden="true" />
      <strong className="text-sm font-semibold">{title}</strong>
      <p className="m-0 max-w-lg text-sm text-muted-foreground">{text}</p>
    </div>
  )
}
