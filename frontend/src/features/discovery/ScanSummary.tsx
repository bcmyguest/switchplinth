// Discovery result banner: the completion or failure summary with a dismiss action; failures are announced as alerts.
import { Activity, X } from 'lucide-react'
import type { Discovery } from './useDiscovery'
import { Alert } from '../../components/ui/alert'
import { Button } from '../../components/ui/button'

type ScanSummaryProps = {
  discovery: Pick<Discovery, 'scanState' | 'summary' | 'dismissSummary'>
}

export function ScanSummary({ discovery }: ScanSummaryProps) {
  const { scanState, summary: scanSummary } = discovery
  if (!scanSummary) return null
  // The Alert role follows the variant: a failure is an alert, a completion a status.
  return <Alert variant={scanState === 'error' || scanState === 'refresh-error' ? 'destructive' : 'default'} className="scan-summary -mt-[9px] mb-[15px] flex items-center gap-[7px] px-[10px] py-[8px] [&>svg]:flex-none"><Activity size={14} /><span className="flex-1">{scanSummary}</span><Button variant="icon" size="icon" className="p-0 text-inherit" aria-label="Dismiss discovery result" onClick={discovery.dismissSummary}><X size={13} /></Button></Alert>
}
