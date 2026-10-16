// Repository chooser dialog: lists the mounted workspace's repositories and switches to the chosen one.
import { GitFork, LoaderCircle, X } from 'lucide-react'
import { Dialog } from '../../components/ui/dialog'
import type { RepositorySwitch } from './useRepositorySwitch'
import { InlineError } from '../../components/InlineError'
import { Button } from '../../components/ui/button'

type RepositoryPickerDialogProps = {
  picker: RepositorySwitch['dialog']
  projectName: string
  projectRoot: string
}

export function RepositoryPickerDialog({ picker, projectName, projectRoot }: RepositoryPickerDialogProps) {
  const { open: showRepositoryPicker, setOpen: setShowRepositoryPicker, repositories, busy: repositoryBusy, error: repositoryError, switchTo: switchRepository } = picker
  return <Dialog open={showRepositoryPicker} onOpenChange={setShowRepositoryPicker} ariaLabel="Open repository"><section className="settings-modal repository-modal">
    <div className="modal-head"><div><span className="modal-icon"><GitFork size={17} /></span><div><h2>Open repository</h2><p>Select an available repository from the mounted workspace.</p></div></div><Button variant="icon" size="icon" aria-label="Close" onClick={() => setShowRepositoryPicker(false)}><X size={17} /></Button></div>
    <div className="current-repository"><span>Current repository</span><strong>{projectName}</strong><code>{projectRoot || 'Mounted repository'}</code></div>
    {repositoryError && <InlineError message={repositoryError} />}
    {repositories.length ? <div className="repository-picker">{repositories.map((repository) => <Button variant="choice" className="min-w-0 gap-[8px] p-[8px] text-(--theme-muted)" key={repository.path} disabled={repositoryBusy} onClick={() => void switchRepository(repository.path)}><GitFork size={14} /><span className="grid min-w-0 flex-1 gap-[3px]"><strong className="overflow-hidden text-(length:--type-tertiary) text-ellipsis whitespace-nowrap text-(--theme-source)">{repository.name}</strong><small className="overflow-hidden font-['DM_Mono',monospace] text-(length:--type-tertiary) text-ellipsis whitespace-nowrap text-(--theme-muted)">{repository.path}</small></span>{repositoryBusy && <LoaderCircle className="spin" size={13} />}</Button>)}</div> : !repositoryError ? <div className="empty-state">Searching the mounted workspace for available repositories…</div> : null}
    <div className="form-actions"><Button variant="subtle" onClick={() => setShowRepositoryPicker(false)}>Close</Button></div>
  </section></Dialog>
}
