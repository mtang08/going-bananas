import { Footprints } from 'lucide-react'

export function Stat({ label, value, sub, icon: Icon }: { label: string; value: string; sub: string; icon: typeof Footprints }) { return <div className="stat"><div className="stat-top"><span>{label}</span><Icon size={19} strokeWidth={1.7}/></div><strong>{value}</strong><small>{sub}</small></div> }
