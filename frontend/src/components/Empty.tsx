import { CircleHelp } from 'lucide-react'

export function Empty({ title, text }: { title: string; text: string }) { return <div className="empty"><CircleHelp size={23}/><strong>{title}</strong><p>{text}</p></div> }
