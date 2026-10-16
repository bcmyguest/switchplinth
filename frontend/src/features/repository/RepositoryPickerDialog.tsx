// Repository chooser dialog: lists the mounted workspace's repositories and switches to the chosen one.
import { AlertTriangle, GitFork, LoaderCircle, X } from 'lucide-react'
import { Dialog } from '../../components/ui/dialog'
import type { RepositorySwitch } from './useRepositorySwitch'

type RepositoryPickerDialogProps = {
  picker: RepositorySwitch['dialog']
  projectName: string
  projectRoot: string
}

export function RepositoryPickerDialog({ picker, projectName, projectRoot }: RepositoryPickerDialogProps) {
  const { open: showRepositoryPicker, setOpen: setShowRepositoryPicker, repositories, busy: repositoryBusy, error: repositoryError, switchTo: switchRepository } = picker
  return <Dialog open={showRepositoryPicker} onOpenChange={setShowRepositoryPicker} ariaLabel="Open repository"><section className="settings-modal repository-modal">
    <div className="modal-head"><div><span className="modal-icon"><GitFork size={17} /></span><div><h2>Open repository</h2><p>Select an available repository from the mounted workspace.</p></div></div><button className="icon-button" onClick={() => setShowRepositoryPicker(false)}><X size={17} /></button></div>
    <div className="current-repository"><span>Current repository</span><strong>{projectName}</strong><code>{projectRoot || 'Mounted repository'}</code></div>
    {repositoryError && <div className="inline-error"><AlertTriangle size={13} />{repositoryError}</div>}
    {repositories.length ? <div className="repository-picker">{repositories.map((repository) => <button key={repository.path} disabled={repositoryBusy} onClick={() => void switchRepository(repository.path)}><GitFork size={14} /><span><strong>{repository.name}</strong><small>{repository.path}</small></span>{repositoryBusy && <LoaderCircle className="spin" size={13} />}</button>)}</div> : !repositoryError ? <div className="empty-state">Searching the mounted workspace for available repositories…</div> : null}
    <div className="form-actions"><button className="button subtle" onClick={() => setShowRepositoryPicker(false)}>Close</button></div>
  </section></Dialog>
}
