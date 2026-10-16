// Source evidence dialog: the open passage, its full source document with the passage highlighted, and its identity fields.
import { AlertTriangle, FileText, LoaderCircle, X } from 'lucide-react'
import { Dialog } from '../../components/ui/dialog'
import { evidenceHeading, evidencePath, evidenceText } from './evidence'
import type { EvidenceViewer } from './useEvidenceViewer'
import { Button } from '../../components/ui/button'

export function SourceEvidenceDialog({ viewer }: { viewer: EvidenceViewer }) {
  const { evidence: activeEvidence, document: sourceDocument, busy: sourceDocumentBusy, error: sourceDocumentError, highlightedLines, firstHighlightedLine, highlightRef } = viewer.dialog
  const closeEvidenceDetail = viewer.close
  return <Dialog open={viewer.isOpen} onOpenChange={(open) => { if (open) viewer.dialog.reopen(); else closeEvidenceDetail() }} onCloseAutoFocus={(event) => event.preventDefault()} ariaLabel="Source evidence"><section className="settings-modal evidence-modal">
      <div className="modal-head"><div><span className="modal-icon"><FileText size={17} /></span><div><h2>Source evidence</h2><p>{evidencePath(activeEvidence)} · {evidenceHeading(activeEvidence)}</p></div></div><Button variant="icon" size="icon" aria-label="Close" onClick={closeEvidenceDetail}><X size={17} /></Button></div>
      <blockquote className="source-passage">{evidenceText(activeEvidence)}</blockquote>
      <div className="source-document-section"><div className="source-document-heading"><strong>Full source document</strong><span>Repository Markdown · {sourceDocument?.path ?? evidencePath(activeEvidence)}</span></div>{sourceDocumentBusy ? <div className="source-document-message"><LoaderCircle className="spin" size={14} /> Loading source document…</div> : sourceDocumentError ? <div className="source-document-message error"><AlertTriangle size={14} /> Could not load {evidencePath(activeEvidence)}: {sourceDocumentError}</div> : sourceDocument ? <pre className="source-document-content">{sourceDocument.content.split('\n').map((line, index) => <span key={index} ref={index === firstHighlightedLine ? highlightRef : undefined} className={highlightedLines.has(index) ? 'source-line highlighted' : 'source-line'}>{line || ' '}{'\n'}</span>)}</pre> : null}</div>
      {activeEvidence?.id && <div className="evidence-identity"><span>Evidence ID</span><code>{activeEvidence.id}</code></div>}
      {activeEvidence?.anchor && <div className="evidence-identity"><span>Anchor</span><code>{activeEvidence.anchor}</code></div>}
      {activeEvidence?.location?.normalized_passage_sha256 && <div className="evidence-identity"><span>Passage hash</span><code>{activeEvidence.location.normalized_passage_sha256}</code></div>}
      {activeEvidence?.source?.content_sha256 && <div className="evidence-identity"><span>Content hash</span><code>{activeEvidence.source.content_sha256}</code></div>}
      {activeEvidence?.source?.git_blob && <div className="evidence-identity"><span>Git blob</span><code>{activeEvidence.source.git_blob}</code></div>}
      {activeEvidence?.location?.display_line != null && <div className="evidence-identity"><span>Display line (hint)</span><code>{activeEvidence.location.display_line}</code></div>}
      <div className="form-actions"><Button variant="subtle" onClick={closeEvidenceDetail}>Close</Button></div>
    </section></Dialog>
}
