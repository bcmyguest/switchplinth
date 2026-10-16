import { AlertTriangle, History, LoaderCircle, RotateCw, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '../../components/ui/alert'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../../components/ui/card'
import {
  JUDGMENT_LABELS,
  REVIEW_KINDS,
  ReviewLogRequestError,
  entryStatus,
  formatReviewedAt,
  getReviewLog,
  priorEffectiveItems,
  priorItemLabel,
  undoReview,
  type ReviewKind,
  type ReviewLogEntry,
  type UndoResult,
} from './reviewLog'

const FILTERS = ['all', ...REVIEW_KINDS] as const
const FILTER_LABELS: Record<ReviewFilter, string> = { all: 'All', claim: 'Claims', alias: 'Aliases', identity: 'Identity' }
const KIND_LABELS: Record<ReviewKind, string> = { claim: 'Claim', alias: 'Alias', identity: 'Identity link' }
// App CSS is unlayered and overrides Tailwind utilities on `ui-button-*`; `!` keeps these action buttons readable in both themes.
const ACTION_BUTTON = 'inline-flex! items-center gap-1.5! rounded-md border border-(--theme-line) bg-(--theme-panel)! px-3! text-(length:--type-control)! font-semibold text-(--theme-ink) hover:bg-(--theme-hover)! disabled:cursor-not-allowed! disabled:opacity-60'

type ReviewFilter = typeof FILTERS[number]

type ReviewLogPanelProps = {
  /** False in sample mode; the panel then makes no API calls. */
  live: boolean
  /** Any value that changes after a review, scan, or repository switch (App passes `graph`); a change refetches the log. */
  revision: unknown
  /** Called after a successful undo so the caller can refresh graph state. */
  onChanged: () => Promise<void> | void
}

type UndoNotice = { entryId: string; tone: 'default' | 'destructive'; title: string; detail: string }

function describeUndo(result: UndoResult): string {
  if (result.already_undone) return `${result.undone_record_id} was already undone.`
  const restored = result.restored_record_ids.length ? result.restored_record_ids.join(', ') : 'the unreviewed suggestion'
  return `Appended ${result.undo.id}; restored ${restored}.`
}

function PriorState({ entry }: { entry: ReviewLogEntry }) {
  const items = priorEffectiveItems(entry)
  return <div className="grid gap-1 text-sm">
    <span className="text-xs font-medium uppercase tracking-wide text-(--theme-muted)">Was</span>
    {items.length === 0
      ? <span className="text-(--theme-muted)">Unreviewed suggestion</span>
      : <ul className="grid gap-1">{items.map((item) => <li key={item.id} className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <Badge variant={item.judgment === 'undo' ? 'outline' : 'secondary'}>{priorItemLabel(item)}</Badge>
        <span className="min-w-0 break-words">{item.summary ?? 'Record not found'}</span>
        <code className="min-w-0 break-all text-xs text-(--theme-muted)">{item.id}</code>
      </li>)}</ul>}
  </div>
}

export function ReviewLogPanel({ live, revision, onChanged }: ReviewLogPanelProps) {
  const [entries, setEntries] = useState<ReviewLogEntry[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [filter, setFilter] = useState<ReviewFilter>('all')
  const [busyId, setBusyId] = useState('')
  const [notice, setNotice] = useState<UndoNotice | null>(null)
  const requestId = useRef(0)

  const load = useCallback(async () => {
    const current = ++requestId.current
    setLoading(true)
    try {
      const next = await getReviewLog()
      if (current !== requestId.current) return
      setEntries(next)
      setLoaded(true)
      setLoadError('')
    } catch (error) {
      if (current !== requestId.current) return
      setLoadError(error instanceof Error ? error.message : String(error))
    } finally {
      if (current === requestId.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!live) {
      requestId.current += 1
      setEntries([])
      setLoaded(false)
      setLoadError('')
      setLoading(false)
      setNotice(null)
      return
    }
    void load()
  }, [live, revision, load])

  async function undo(entry: ReviewLogEntry) {
    setBusyId(entry.id)
    setNotice(null)
    try {
      const result = await undoReview(entry.id)
      setNotice({ entryId: entry.id, tone: 'default', title: result.already_undone ? 'Already undone' : 'Judgment undone', detail: describeUndo(result) })
      await onChanged()
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error)
      const title = error instanceof ReviewLogRequestError && error.status === 409 ? 'Undo not allowed' : error instanceof ReviewLogRequestError && error.status === 404 ? 'Review record not found' : 'Undo failed'
      setNotice({ entryId: entry.id, tone: 'destructive', title, detail })
    } finally {
      setBusyId('')
      await load()
    }
  }

  const counts: Record<ReviewFilter, number> = { all: entries.length, claim: 0, alias: 0, identity: 0 }
  for (const entry of entries) counts[entry.kind] += 1
  const visible = filter === 'all' ? entries : entries.filter((entry) => entry.kind === filter)

  return <section id="review-log" aria-labelledby="review-log-title" className="grid gap-3">
    <div className="section-heading">
      <div><div className="section-kicker">APPEND-ONLY HISTORY</div><h2 id="review-log-title">Review log <span>{entries.length}</span></h2></div>
      {live && <Button type="button" variant="ghost" size="sm" className={ACTION_BUTTON} disabled={loading} onClick={() => void load()}>{loading ? <LoaderCircle className="spin" size={13} /> : <RotateCw size={13} />} Refresh</Button>}
    </div>
    <p className="text-sm text-(--theme-muted)">Human claim, alias, and identity judgments, newest first. Undo appends a record that restores the earlier state; to redo, review the item again above.</p>
    {!live && <Alert><History /><AlertDescription>Open a repository to see its review history.</AlertDescription></Alert>}
    {live && <>
      <nav className="facts-filters" aria-label="Filter review log">{FILTERS.map((value) => <Button type="button" key={value} size="sm" variant={filter === value ? 'secondary' : 'ghost'} aria-pressed={filter === value} onClick={() => setFilter(value)}>{FILTER_LABELS[value]} · {counts[value]}</Button>)}</nav>
      {loadError && <Alert variant="destructive"><AlertTriangle /><AlertTitle>Review log did not load</AlertTitle><AlertDescription><p>{loadError}</p><Button type="button" variant="secondary" size="sm" className={ACTION_BUTTON} onClick={() => void load()}>Retry</Button></AlertDescription></Alert>}
      {notice && !entries.some((entry) => entry.id === notice.entryId) && <Alert variant={notice.tone}><AlertTitle>{notice.title}</AlertTitle><AlertDescription>{notice.detail}</AlertDescription></Alert>}
      {!loaded && loading && <p className="text-sm text-(--theme-muted)">Loading review log…</p>}
      {loaded && visible.length === 0 && <p className="text-sm text-(--theme-muted)">{entries.length === 0 ? 'No human judgments recorded yet.' : `No ${FILTER_LABELS[filter].toLowerCase()} judgments recorded.`}</p>}
      <ol className="grid gap-3" aria-label="Review judgments">{visible.map((entry) => {
        const reasonId = `review-log-reason-${entry.id}`
        const isUndo = entry.judgment === 'undo'
        const blocked = !entry.undoable
        return <li key={entry.id}>
          <Card className="gap-3 py-4" data-review-entry={entry.id}>
            <CardHeader className="px-4">
              <CardTitle className="min-w-0 break-words leading-snug">{entry.summary}</CardTitle>
              <CardDescription className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <Badge variant="outline">{KIND_LABELS[entry.kind]}</Badge>
                <Badge variant={isUndo ? 'outline' : entry.effective ? 'secondary' : 'warning'}>{JUDGMENT_LABELS[entry.judgment]}</Badge>
                <span>{formatReviewedAt(entry.reviewed_at)}</span>
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3 px-4">
              <PriorState entry={entry} />
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="grid min-w-0 gap-0.5 text-sm">
                  <span className="font-medium">{entryStatus(entry)}</span>
                  <code className="min-w-0 break-all text-xs text-(--theme-muted)">{entry.id}</code>
                </div>
                <Button type="button" variant="secondary" size="sm" className={ACTION_BUTTON} disabled={!entry.undoable || busyId !== ''} aria-describedby={blocked ? reasonId : undefined} onClick={() => void undo(entry)}>
                  {busyId === entry.id ? <LoaderCircle className="spin" size={13} /> : <Undo2 size={13} />} Undo
                </Button>
              </div>
              {blocked && entry.undo_blocked_reason && <p id={reasonId} className="text-xs text-(--theme-muted)">{entry.undo_blocked_reason}</p>}
              {notice?.entryId === entry.id && <Alert variant={notice.tone}><AlertTitle>{notice.title}</AlertTitle><AlertDescription>{notice.detail}</AlertDescription></Alert>}
            </CardContent>
          </Card>
        </li>
      })}</ol>
    </>}
  </section>
}
