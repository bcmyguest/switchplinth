// Map card for one architecture entity, with connect handles and its epistemic-state badge.
import { Handle, Position } from '@xyflow/react'
import { Check } from 'lucide-react'

const KIND_ICONS: Record<string, string> = { service: 'S', technology: 'T', datastore: 'D', queue: 'Q', interface: 'I' }

export function ArchitectureNode({ data }: { data: { label: string; title?: string; kind: string; status: string; confidence?: number; targetPosition?: Position; sourcePosition?: Position } }) {
  return <div className={`arch-node ${data.kind}`} title={data.title ?? data.label}>
    <Handle type="target" position={data.targetPosition ?? Position.Left} aria-label={`Connect to ${data.label}`} />
    <div className="node-mark">{KIND_ICONS[data.kind] ?? '•'}</div>
    <div className="node-copy"><span>{data.kind}</span><strong>{data.label}</strong></div>
    <div className={`node-state ${data.status}`} title={`${data.status}${data.confidence ? ` · ${Math.round(data.confidence * 100)}% confidence` : ''}`}>{data.status === 'confirmed' ? <Check size={11} /> : <span />}</div>
    <Handle type="source" position={data.sourcePosition ?? Position.Right} aria-label={`Connect from ${data.label}`} />
  </div>
}
