import type { Capability, Claim, Connection, Entity, EntityDecisionDetail, GraphData, IdentityConflict, IdentityGroup, IdentitySuggestion, SavedScenario } from './types'

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

export type SearchEvidence = { id?: string; path?: string; source?: string; passage?: string; text?: string; heading?: string | string[]; location?: { heading_path?: string[] } }
export type SearchInactiveEntity = { id: string; name: string }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json() as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail !== undefined) detail = JSON.stringify(body.detail)
    } catch { /* Keep the HTTP status when the response has no JSON body. */ }
    throw new Error(detail)
  }
  return response.json() as Promise<T>
}

export async function getGraph(): Promise<GraphData> {
  return request<GraphData>('/graph')
}

export async function scanRepository() {
  return request<{ documents?: Array<{ path: string }>; document_count?: number; candidate_decision_count?: number; candidate_claim_count?: number; index?: { qdrant: string } }>('/discovery/scan', { method: 'POST', body: '{}' })
}

export async function extractWithProvider(connectionId: string) {
  return request<{ provider: string; model: string; document_count: number; passage_count: number; entity_count: number; alias_count: number; claim_count: number; relationship_count: number; consequence_count: number; decision_count: number; diagnostics: string[]; index: { qdrant: string } }>('/extraction/run', { method: 'POST', body: JSON.stringify({ connection_id: connectionId }) })
}

export async function getConnections(): Promise<Connection[]> {
  return request<Connection[]>('/connections')
}

export async function getProject() {
  return request<{ name: string; root: string; format_version: string }>('/project')
}

export async function getSourceDocument(path: string) {
  return request<{ path: string; content: string }>(`/source?${new URLSearchParams({ path }).toString()}`)
}

export async function getRepositories() {
  return request<{ workspace: string; repositories: Array<{ path: string; name: string }> }>('/repositories')
}

export async function openProject(path: string) {
  return request<{ project: { name: string; root: string; format_version: string } }>('/project/open', { method: 'POST', body: JSON.stringify({ path }) })
}

export async function testConnection(id: string) {
  return request<{ id: string; latency_ms?: number; capabilities: Record<string, Capability> }>(`/connections/${id}/test`, { method: 'POST', body: '{}' })
}

export async function saveConnection(connection: Omit<Connection, 'status' | 'diagnostics' | 'capabilities'>) {
  return request<Connection>('/connections', { method: 'POST', body: JSON.stringify(connection) })
}

export async function resolveScenario(selections: Record<string, string>) {
  return request<{ graph: GraphData; affected?: { added?: string[]; removed?: string[]; changed?: string[] }; conflicts?: string[]; invalid_assumptions?: string[] }>('/scenarios/resolve', { method: 'POST', body: JSON.stringify({ selections }) })
}

export async function previewOptionDelta(decisionId: string, optionId: string, delta: NonNullable<GraphData['decisions'][number]['options'][number]['delta']>, selections: Record<string, string>) {
  return request<{ graph: GraphData; affected?: { added?: string[]; removed?: string[]; changed?: string[] }; conflicts?: string[]; invalid_assumptions?: string[] }>(
    '/scenarios/preview-delta',
    { method: 'POST', body: JSON.stringify({ decision_id: decisionId, option_id: optionId, delta, selections }) },
  )
}

export async function saveScenario(name: string, selections: Record<string, string>, expectedProjectRoot?: string) {
  return request<{ id: string; name: string; selections: Record<string, string> }>('/scenarios', { method: 'POST', body: JSON.stringify({ name, selections, ...(expectedProjectRoot ? { expected_project_root: expectedProjectRoot } : {}) }) })
}

export async function listScenarios(): Promise<SavedScenario[]> {
  return request<SavedScenario[]>('/scenarios')
}

export async function searchArchitecture(query: string, selections: Record<string, string> = {}) {
  return request<{ answer: string; grounded?: boolean; evidence?: SearchEvidence[]; claims?: Claim[]; entities?: string[]; scenario_context?: { inactive_entities?: SearchInactiveEntity[] } }>('/search', { method: 'POST', body: JSON.stringify({ query, selections }) })
}

export async function proposeScenarioChange(decisionId: string, optionId: string, requestText: string, connectionId?: string) {
  return request<{ delta: NonNullable<GraphData['decisions'][number]['options'][number]['delta']>; rationale?: string; warnings?: string[] }>('/scenarios/propose', { method: 'POST', body: JSON.stringify({ decision_id: decisionId, option_id: optionId, request: requestText, connection_id: connectionId }) })
}

export async function reviewClaim(id: string, epistemicState: 'confirmed' | 'rejected' | 'asserted') {
  return request(`/claims/${id}/review`, { method: 'POST', body: JSON.stringify({ epistemic_state: epistemicState }) })
}

export async function reviewExactIdentityCandidate(entityIds: [string, string], epistemicState: 'confirmed' | 'rejected' | 'asserted') {
  return request('/identity-candidates/review', { method: 'POST', body: JSON.stringify({ entity_ids: entityIds, epistemic_state: epistemicState }) })
}

export async function reviewAlias(id: string, epistemicState: 'confirmed' | 'rejected' | 'asserted') {
  return request(`/aliases/${id}/review`, { method: 'POST', body: JSON.stringify({ epistemic_state: epistemicState }) })
}

export async function correctClaim(id: string, correction: { subject: string; predicate: string; object: string }) {
  return request(`/claims/${encodeURIComponent(id)}/correct`, { method: 'POST', body: JSON.stringify(correction) })
}

export async function correctAlias(id: string, correction: { name: string; entity_id: string }) {
  return request(`/aliases/${encodeURIComponent(id)}/correct`, { method: 'POST', body: JSON.stringify(correction) })
}

export async function getEntityDetail(id: string, selections: Record<string, string> = {}) {
  const query = new URLSearchParams({ selections: JSON.stringify(selections) })
  return request<{ entity: Entity; relationships: GraphData['relationships']; decisions: EntityDecisionDetail[]; aliases: NonNullable<GraphData['aliases']>; claims: NonNullable<GraphData['claims']>; evidence: NonNullable<GraphData['evidence']>; identity_groups: IdentityGroup[]; identity_suggestions: IdentitySuggestion[]; identity_conflicts: IdentityConflict[] }>(`/entities/${encodeURIComponent(id)}?${query.toString()}`)
}

export async function saveOptionDelta(decisionId: string, optionId: string, delta: NonNullable<GraphData['decisions'][number]['options'][number]['delta']>) {
  return request(`/decisions/${decisionId}/options/${optionId}`, { method: 'PATCH', body: JSON.stringify({ delta }) })
}
