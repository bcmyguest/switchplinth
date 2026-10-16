// Map card for one architecture entity, with connect handles and its epistemic-state badge.
import { Handle, Position } from '@xyflow/react'
import { Box, Check, Cpu, Database, Plug, Rows3, Server, type LucideIcon } from 'lucide-react'

const KIND_ICONS: Record<string, LucideIcon> = { service: Server, technology: Cpu, datastore: Database, queue: Rows3, interface: Plug }

export function ArchitectureNode({ data }: { data: { label: string; title?: string; kind: string; status: string; confidence?: number; targetPosition?: Position; sourcePosition?: Position } }) {
  return <div className={`arch-node ${data.kind}`} title={data.title ?? data.label}>
    <Handle type="target" position={data.targetPosition ?? Position.Left} aria-label={`Connect to ${data.label}`} />
    <div className="node-mark">{(() => { const Icon = KIND_ICONS[data.kind] ?? Box; return <Icon size={24} strokeWidth={1.7} aria-hidden /> })()}</div>
    <div className="node-copy"><strong>{data.label}</strong><span>{data.kind}</span></div>
    <div className={`node-state ${data.status}`} title={`${data.status}${data.confidence ? ` · ${Math.round(data.confidence * 100)}% confidence` : ''}`}>{data.status === 'confirmed' ? <Check size={11} /> : <span />}</div>
    <Handle type="source" position={data.sourcePosition ?? Position.Right} aria-label={`Connect from ${data.label}`} />
  </div>
}
