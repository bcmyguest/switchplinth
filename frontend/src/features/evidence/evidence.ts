// Pure helpers for evidence records: labels, source counts, and passage highlighting in a source document.
import type { Evidence } from '../../types'

export function evidencePath(evidence: Evidence | undefined): string {
  return evidence?.path ?? evidence?.source?.path ?? 'Source document'
}

export function currentSourceCount(evidence: Evidence[] | undefined): number {
  return new Set((evidence ?? []).filter((item) => item.state === undefined || item.state === 'current').map(evidencePath)).size
}

export function evidenceHeading(evidence: Evidence | undefined): string {
  return evidence?.heading ?? evidence?.location?.heading_path?.join(' / ') ?? 'Source evidence'
}

export function evidenceText(evidence: Evidence | undefined): string {
  return evidence?.passage ?? evidence?.text ?? 'No source passage is attached.'
}

export function highlightedSourceLines(content: string, evidence: Evidence | undefined): Set<number> {
  const lines = content.split('\n')
  const passage = evidenceText(evidence).trim().toLocaleLowerCase().replace(/\s+/g, ' ')
  if (evidence && passage && passage !== 'no source passage is attached.') {
    let start = 0
    while (start < lines.length) {
      while (start < lines.length && !lines[start].trim()) start += 1
      if (start === lines.length) break
      let end = start
      while (end + 1 < lines.length && lines[end + 1].trim()) end += 1
      const block = lines.slice(start, end + 1).join(' ').toLocaleLowerCase().replace(/\s+/g, ' ').trim()
      if (block.includes(passage)) return new Set(Array.from({ length: end - start + 1 }, (_, index) => start + index))
      start = end + 1
    }
  }
  const headings = evidence?.location?.heading_path ?? (evidence?.heading ? [evidence.heading] : [])
  const heading = headings.at(-1)?.trim().toLocaleLowerCase()
  const headingIndex = heading ? lines.findIndex((line) => line.replace(/^\s*#{1,6}\s+/, '').trim().toLocaleLowerCase() === heading) : -1
  return headingIndex >= 0 ? new Set([headingIndex]) : new Set()
}

export function resolveEvidence(reference: Evidence | string | undefined, records: Evidence[] = []): Evidence | undefined {
  return typeof reference === 'string' ? records.find((item) => item.id === reference) : reference
}
