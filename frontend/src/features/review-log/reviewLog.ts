const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export const REVIEW_KINDS = ['claim', 'alias', 'identity'] as const
export const JUDGMENT_LABELS: Record<ReviewJudgment, string> = {
  confirmed: 'Confirmed',
  rejected: 'Rejected',
  asserted: 'Asserted',
  corrected: 'Corrected',
  undo: 'Undo',
}

export type ReviewKind = typeof REVIEW_KINDS[number]
export type ReviewJudgment = 'confirmed' | 'rejected' | 'asserted' | 'corrected' | 'undo'

/** One record this judgment replaced; every field except `id` is null when the ID does not resolve. */
export type ReviewPriorItem = {
  id: string
  epistemic_state: string | null
  judgment: ReviewJudgment | null
  summary: string | null
  subject: unknown
}

export type ReviewLogEntry = {
  id: string
  record_type?: string
  kind: ReviewKind
  judgment: ReviewJudgment
  epistemic_state?: string
  summary: string
  subject?: unknown
  reviewed_record?: string | null
  supersedes: string[]
  undoes: string | null
  undone_by: string | null
  superseded_by: string | null
  reviewed_at?: string | null
  reviewer?: string | null
  effective: boolean
  undoable: boolean
  undo_blocked_reason: string | null
  prior: ReviewPriorItem[]
  prior_effective: string[]
}

export type UndoResult = {
  undo: { id: string }
  undone_record_id: string
  restored_record_ids: string[]
  already_undone: boolean
  kind: ReviewKind
}

/** Fetch failure that keeps the HTTP status, so callers can tell a 409 conflict from other errors. */
export class ReviewLogRequestError extends Error {
  readonly status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ReviewLogRequestError'
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail !== undefined) detail = JSON.stringify(body.detail)
    } catch { /* Keep the HTTP status when the response has no JSON body. */ }
    throw new ReviewLogRequestError(response.status, detail)
  }
  return response.json() as Promise<T>
}

export async function getReviewLog(): Promise<ReviewLogEntry[]> {
  return (await request<{ entries: ReviewLogEntry[] }>('/reviews')).entries
}

export async function undoReview(id: string): Promise<UndoResult> {
  return request<UndoResult>(`/reviews/${encodeURIComponent(id)}/undo`, { method: 'POST', body: '{}' })
}

/** Records that were effective immediately before the entry; empty means an unreviewed suggestion. */
export function priorEffectiveItems(entry: ReviewLogEntry): ReviewPriorItem[] {
  const byId = new Map(entry.prior.map((item) => [item.id, item]))
  return entry.prior_effective.map((id) => byId.get(id) ?? { id, epistemic_state: null, judgment: null, summary: null, subject: null })
}

export function priorItemLabel(item: ReviewPriorItem): string {
  if (item.judgment) return item.judgment === 'undo' ? 'Undo record' : JUDGMENT_LABELS[item.judgment]
  if (item.epistemic_state === null) return 'Unresolved record'
  return item.epistemic_state === 'inferred' ? 'Original inference' : item.epistemic_state
}

export function entryStatus(entry: ReviewLogEntry): string {
  if (entry.judgment === 'undo') return entry.undoes ? `Undo record · reverted ${entry.undoes}` : 'Undo record'
  if (entry.undone_by) return `Undone by ${entry.undone_by}`
  if (entry.effective) return 'Effective'
  if (entry.superseded_by) return `Superseded by ${entry.superseded_by}`
  return 'Not effective'
}

export function formatReviewedAt(value: string | null | undefined): string {
  if (!value) return 'Time not recorded'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}
