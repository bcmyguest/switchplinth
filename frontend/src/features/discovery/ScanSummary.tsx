// Discovery result banner: the completion or failure summary with a dismiss action; failures are announced as alerts.
import { Activity, X } from 'lucide-react'
import type { Discovery } from './useDiscovery'

type ScanSummaryProps = {
  discovery: Pick<Discovery, 'scanState' | 'summary' | 'dismissSummary'>
}

export function ScanSummary({ discovery }: ScanSummaryProps) {
  const { scanState, summary: scanSummary } = discovery
  if (!scanSummary) return null
  return <div className={`scan-summary ${scanState === 'error' || scanState === 'refresh-error' ? 'error' : ''}`} role={scanState === 'error' || scanState === 'refresh-error' ? 'alert' : 'status'}><Activity size={14} />{scanSummary}<button aria-label="Dismiss discovery result" onClick={discovery.dismissSummary}><X size={13} /></button></div>
}
