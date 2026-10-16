// Discovery mode chooser: deterministic/mock or configured-model extraction, the model connection for provider runs, and
// the run action. Every Discover trigger opens this one dialog.
import { Sparkles, X } from 'lucide-react'
import { Dialog } from '../../components/ui/dialog'
import { Radio } from '../../components/ui/radio'
import type { Connections } from '../settings/useConnections'
import type { Discovery } from './useDiscovery'
import { InlineError } from '../../components/InlineError'
import { Button } from '../../components/ui/button'
import { Select } from '../../components/ui/select'

type DiscoverDialogProps = {
  discovery: Discovery
  connections: Pick<Connections, 'list' | 'selectedId' | 'select' | 'openSettings'>
}

export function DiscoverDialog({ discovery, connections }: DiscoverDialogProps) {
  const { scanState } = discovery
  const { open: showDiscoverDialog, setOpen: setShowDiscoverDialog, mode: discoverMode, setMode: setDiscoverMode } = discovery.dialog
  return <Dialog open={showDiscoverDialog} onOpenChange={setShowDiscoverDialog} ariaLabel="Choose discovery mode"><section className="settings-modal discover-modal">
    <div className="modal-head"><div><span className="modal-icon"><Sparkles size={17} /></span><div><h2>Discover this repository</h2><p>Choose how Markdown sources should be processed.</p></div></div><Button variant="icon" size="icon" aria-label="Close discovery choices" onClick={() => setShowDiscoverDialog(false)}><X size={17} /></Button></div>
    <fieldset className="discover-modes"><legend>Extraction mode</legend>
      <label><Radio name="discover-mode" checked={discoverMode === 'mock'} onChange={() => setDiscoverMode('mock')} /><span><strong>Deterministic / mock</strong><small>Use local rules and the repeatable mock extractor.</small></span></label>
      <label><Radio name="discover-mode" checked={discoverMode === 'provider'} onChange={() => setDiscoverMode('provider')} disabled={!connections.list.length} /><span><strong>Configured model</strong><small>Extract through the selected provider connection.</small></span></label>
    </fieldset>
    {discoverMode === 'provider' && (connections.list.length ? <label className="discover-connection">Model connection<Select aria-label="Model connection" className="min-h-[32px] rounded-[5px] border border-(--theme-line) bg-(--theme-panel) px-[8px] text-[13px] text-(--theme-muted)" value={connections.list.some((item) => item.id === connections.selectedId) ? connections.selectedId : connections.list[0].id} onChange={(event) => connections.select(event.target.value)}>{connections.list.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.provider} · {connection.model}</option>)}</Select><small>The selected provider and model will be shown with the result.</small></label> : <InlineError message={<p>No model connections are configured. <Button variant="link" className="inline min-h-0 p-0" onClick={() => { setShowDiscoverDialog(false); connections.openSettings() }}>Configure a connection</Button> to use provider extraction.</p>} />)}
    <div className="form-actions"><Button variant="subtle" onClick={() => setShowDiscoverDialog(false)}>Cancel</Button><Button className="text-(length:--type-tertiary)" disabled={scanState === 'scanning' || (discoverMode === 'provider' && !connections.list.length)} onClick={() => void discovery.run()}><Sparkles size={13} />Run discovery</Button></div>
  </section></Dialog>
}
