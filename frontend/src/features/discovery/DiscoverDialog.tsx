// Discovery mode chooser: deterministic/mock or configured-model extraction, the model connection for provider runs, and
// the run action. Every Discover trigger opens this one dialog.
import { AlertTriangle, Sparkles, X } from 'lucide-react'
import { Dialog } from '../../components/ui/dialog'
import type { Connections } from '../settings/useConnections'
import type { Discovery } from './useDiscovery'

type DiscoverDialogProps = {
  discovery: Discovery
  connections: Pick<Connections, 'list' | 'selectedId' | 'select' | 'openSettings'>
}

export function DiscoverDialog({ discovery, connections }: DiscoverDialogProps) {
  const { scanState } = discovery
  const { open: showDiscoverDialog, setOpen: setShowDiscoverDialog, mode: discoverMode, setMode: setDiscoverMode } = discovery.dialog
  return <Dialog open={showDiscoverDialog} onOpenChange={setShowDiscoverDialog} ariaLabel="Choose discovery mode"><section className="settings-modal discover-modal">
    <div className="modal-head"><div><span className="modal-icon"><Sparkles size={17} /></span><div><h2>Discover this repository</h2><p>Choose how Markdown sources should be processed.</p></div></div><button className="icon-button" aria-label="Close discovery choices" onClick={() => setShowDiscoverDialog(false)}><X size={17} /></button></div>
    <fieldset className="discover-modes"><legend>Extraction mode</legend>
      <label><input type="radio" name="discover-mode" checked={discoverMode === 'mock'} onChange={() => setDiscoverMode('mock')} /><span><strong>Deterministic / mock</strong><small>Use local rules and the repeatable mock extractor.</small></span></label>
      <label><input type="radio" name="discover-mode" checked={discoverMode === 'provider'} onChange={() => setDiscoverMode('provider')} disabled={!connections.list.length} /><span><strong>Configured model</strong><small>Extract through the selected provider connection.</small></span></label>
    </fieldset>
    {discoverMode === 'provider' && (connections.list.length ? <label className="discover-connection">Model connection<select aria-label="Model connection" value={connections.list.some((item) => item.id === connections.selectedId) ? connections.selectedId : connections.list[0].id} onChange={(event) => connections.select(event.target.value)}>{connections.list.map((connection) => <option key={connection.id} value={connection.id}>{connection.name} · {connection.provider} · {connection.model}</option>)}</select><small>The selected provider and model will be shown with the result.</small></label> : <div className="inline-error"><AlertTriangle size={13} />No model connections are configured. <button className="text-button" onClick={() => { setShowDiscoverDialog(false); connections.openSettings() }}>Configure a connection</button> to use provider extraction.</div>)}
    <div className="form-actions"><button className="button subtle" onClick={() => setShowDiscoverDialog(false)}>Cancel</button><button className="button primary" disabled={scanState === 'scanning' || (discoverMode === 'provider' && !connections.list.length)} onClick={() => void discovery.run()}><Sparkles size={13} />Run discovery</button></div>
  </section></Dialog>
}
