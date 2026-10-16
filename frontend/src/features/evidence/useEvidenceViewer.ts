// Source evidence viewer: which passage is open, its source document fetch, the highlighted lines, and opener focus return.
import { useEffect, useRef, useState, type RefObject } from 'react'
import { getSourceDocument, type SearchEvidence } from '../../api'
import type { Evidence } from '../../types'
import { evidenceHeading, evidencePath, highlightedSourceLines, resolveEvidence } from './evidence'

type SourceDocument = { path: string; content: string }

/** State the source dialog renders; only `SourceEvidenceDialog` reads it. */
type EvidenceDialogState = {
  evidence: Evidence | undefined
  document: SourceDocument | null
  busy: boolean
  error: string
  highlightedLines: Set<number>
  firstHighlightedLine: number | undefined
  highlightRef: RefObject<HTMLSpanElement | null>
  reopen: () => void
}

export type EvidenceViewer = {
  isOpen: boolean
  /** Open a passage. Focus returns to `opener`, or to the element focused at call time, when the dialog closes. */
  open: (evidence: Evidence | null | undefined, opener?: HTMLElement) => void
  close: () => void
  /** `path · heading` for an evidence ID in `records`, or undefined when it does not resolve. */
  passageLabel: (evidenceId: string) => string | undefined
  /** Open an evidence ID resolved against `records`. */
  openPassage: (evidenceId: string, opener: HTMLElement) => void
  /** Open a search result passage, preferring the matching graph evidence record. */
  openSearchPassage: (source: SearchEvidence) => void
  dialog: EvidenceDialogState
}

/**
 * `records` resolves evidence IDs (component detail evidence first, then graph evidence);
 * `graphEvidence` matches search passages to graph records. Both are read at call time.
 */
export function useEvidenceViewer(records: Evidence[], graphEvidence: Evidence[] | undefined): EvidenceViewer {
  const [isOpen, setIsOpen] = useState(false)
  const [activeEvidence, setActiveEvidence] = useState<Evidence | undefined>(undefined)
  const [sourceDocument, setSourceDocument] = useState<SourceDocument | null>(null)
  const [sourceDocumentBusy, setSourceDocumentBusy] = useState(false)
  const [sourceDocumentError, setSourceDocumentError] = useState('')
  const openerRef = useRef<HTMLElement | null>(null)
  const highlightRef = useRef<HTMLSpanElement | null>(null)

  useEffect(() => {
    if (!isOpen || !activeEvidence) return
    const path = evidencePath(activeEvidence)
    let cancelled = false
    setSourceDocument(null)
    setSourceDocumentError('')
    setSourceDocumentBusy(true)
    void getSourceDocument(path).then((document) => {
      if (!cancelled) setSourceDocument(document)
    }).catch((error: unknown) => {
      if (!cancelled) setSourceDocumentError(error instanceof Error ? error.message : 'Could not load the source document.')
    }).finally(() => {
      if (!cancelled) setSourceDocumentBusy(false)
    })
    return () => { cancelled = true }
  }, [isOpen, activeEvidence])

  const highlightedLines = sourceDocument ? highlightedSourceLines(sourceDocument.content, activeEvidence) : new Set<number>()
  const firstHighlightedLine = highlightedLines.values().next().value as number | undefined

  useEffect(() => {
    if (!isOpen || !sourceDocument || sourceDocument.path !== evidencePath(activeEvidence) || firstHighlightedLine === undefined) return
    // Scroll only the source pane; scrollIntoView would also scroll the modal and hide its title on mobile.
    const frame = window.requestAnimationFrame(() => {
      const line = highlightRef.current
      const pane = line?.closest<HTMLElement>('.source-document-content')
      if (!line || !pane) return
      const lineTop = line.getBoundingClientRect().top - pane.getBoundingClientRect().top + pane.scrollTop
      pane.scrollTo({ top: Math.max(0, lineTop - (pane.clientHeight - line.offsetHeight) / 2), behavior: 'smooth' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [activeEvidence, firstHighlightedLine, isOpen, sourceDocument])

  function open(evidence: Evidence | null | undefined, opener?: HTMLElement) {
    if (!evidence) return
    const activeElement = document.activeElement
    openerRef.current = opener ?? (activeElement instanceof HTMLElement ? activeElement : null)
    setActiveEvidence(evidence)
    setIsOpen(true)
  }
  function passageLabel(evidenceId: string): string | undefined {
    const evidence = resolveEvidence(evidenceId, records)
    return evidence && `${evidencePath(evidence)} · ${evidenceHeading(evidence)}`
  }
  function openPassage(evidenceId: string, opener: HTMLElement) {
    open(resolveEvidence(evidenceId, records), opener)
  }
  function close() {
    setIsOpen(false)
    const opener = openerRef.current
    openerRef.current = null
    window.setTimeout(() => opener?.focus({ preventScroll: true }), 0)
  }
  function openSearchPassage(source: SearchEvidence) {
    const path = source.path ?? source.source
    if (!path) return
    const existing = graphEvidence?.find((item) => item.id === source.id || evidencePath(item) === path)
    const heading = Array.isArray(source.heading) ? source.heading.join(' / ') : source.heading ?? source.location?.heading_path?.join(' / ')
    open(existing ?? { id: source.id ?? `search-${path}`, path, passage: source.passage ?? source.text ?? '', ...(heading ? { heading } : {}) })
  }

  return {
    isOpen, open, close, passageLabel, openPassage, openSearchPassage,
    dialog: { evidence: activeEvidence, document: sourceDocument, busy: sourceDocumentBusy, error: sourceDocumentError, highlightedLines, firstHighlightedLine, highlightRef, reopen: () => setIsOpen(true) },
  }
}
