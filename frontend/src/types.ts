export type Evidence = {
  id: string
  path: string
  state?: 'current' | 'unresolved'
  heading?: string
  passage: string
  anchor?: string
  source?: { path?: string; content_sha256?: string; git_blob?: string }
  location?: { heading_path?: string[]; display_line?: number; normalized_passage_sha256?: string }
  text?: string
}

export type Claim = {
  id: string
  subject: string
  predicate: string
  object: string
  epistemic_state: 'inferred' | 'confirmed' | 'rejected' | 'asserted'
  confidence: number
  evidence?: string[]
  source_path?: string
  supersedes?: string[]
}

export type IdentityGroup = { entity_ids: string[] }

export type IdentitySuggestion = {
  source: 'inferred_claim' | 'exact_name' | string
  entity_ids: string[]
  epistemic_state?: Claim['epistemic_state']
  claim_id?: string
  evidence?: Array<Evidence | string>
  confidence?: number
  name?: string
  kind?: string
}

export type IdentityConflict = {
  type: string
  entity_ids: string[]
  component_entity_ids?: string[]
  claim_ids?: string[]
}

type Alias = {
  id: string
  name: string
  confidence: number
  epistemic_state: 'inferred' | 'confirmed' | 'rejected' | 'asserted'
  evidence?: Array<Evidence | string>
  supersedes?: string[]
  reviewed_alias?: string
  reviewer?: string
}

export type Entity = {
  id: string
  name: string
  kind: string
  description?: string
  epistemic_state?: string
  confidence?: number
  aliases?: Alias[]
  evidence?: Array<Evidence | string>
}

type Relationship = {
  id: string
  from: string
  to: string
  kind: string
  epistemic_state?: string
  confidence?: number
  claim_id?: string
  evidence?: Evidence[]
}

export type DeltaOperation = {
  op: string
  [key: string]: unknown
}

export type Option = {
  id: string
  title: string
  rationale?: string
  delta?: { base?: string; operations: DeltaOperation[] }
  evidence?: Array<Evidence | string>
}

export type SourceStatement = { text: string; evidence_id: string }

export type Decision = {
  id: string
  title: string
  status?: string
  selected_option?: string
  options: Option[]
  evidence?: Evidence[]
  context?: string
  extraction_review?: {
    status: 'required'
    attempts: number
    rejected_options: Array<{ option_id: string; delta: unknown; errors: string[] }>
  }
  /** Read-only, derived from source passages; follows the saved record's choice, not a What-if preview. */
  derived?: { consequences: SourceStatement[]; rejection_reasons: Record<string, SourceStatement> }
}

export type EntityDecisionDetail = {
  id: string
  title: string
  selected_option?: Option | null
  options: Option[]
}

export type GraphData = {
  entities: Entity[]
  relationships: Relationship[]
  decisions: Decision[]
  claims?: Claim[]
  aliases?: Array<Alias & { entity_id: string }>
  evidence?: Evidence[]
  identity_groups?: IdentityGroup[]
  identity_suggestions?: IdentitySuggestion[]
  identity_conflicts?: IdentityConflict[]
  scenario?: { selections?: Record<string, string>; affected?: { added?: string[]; removed?: string[]; changed?: string[] }; conflicts?: string[]; invalid_assumptions?: string[]; affected_decisions?: string[] }
}

export type SavedScenario = { id: string; name: string; selections: Record<string, string> }

type DiffEntity = { id: string; kind: string; name: string; description?: string }
type DiffRelationship = { id: string; from: string; to: string; kind: string; claim_id?: string | null }
type ChangeSet<T> = { added: T[]; removed: T[]; changed: Array<{ id: string; before: T; after: T }> }
type MissingEndpoint = { relationship_id: string; kind: string; missing_entity_id: string; status: 'rewired' | 'dangling'; rewired_to: Array<{ relationship_id: string; to: string }> }
export type ImpactDependent = { entity_id: string; name: string; depth: number; path: string[]; present_after: boolean; points_at_missing: boolean; rewired: boolean; missing_endpoints: MissingEndpoint[] }
type ImpactReport = { basis: string; max_depth: number; limits: string; items: Array<{ type: 'entity' | 'relationship'; id: string; name: string; change: 'removed' | 'replaced'; dependents: ImpactDependent[]; truncated: boolean }> }

/** `POST /api/v1/scenarios/diff`: how the after scenario differs from the before scenario. */
export type ScenarioDiff = {
  selections: { before: Record<string, string>; after: Record<string, string> }
  selection_changes: Array<{ decision_id: string; before_option: string | null; after_option: string | null }>
  entities: ChangeSet<DiffEntity>
  relationships: ChangeSet<DiffRelationship>
  conflicts: { appeared: string[]; disappeared: string[] }
  invalid_assumptions: { appeared: string[]; disappeared: string[] }
  affected_decisions: Array<{ id: string; title: string; reasons: string[] }>
  impact: ImpactReport
}

export type Capability = { status: 'supported' | 'unsupported' | 'error'; latency_ms?: number; raw_error?: string; normalized_error?: string; detail?: string }

export type ConnectionGeneration = {
  reasoning?: 'off' | 'low' | 'medium' | 'high'
  max_output_tokens?: number
  request_timeout_seconds?: number
}

export type Connection = {
  id: string
  name: string
  provider: string
  endpoint?: string
  model?: string
  embedding_model?: string
  status?: string
  diagnostics?: Record<string, Capability>
  capabilities?: Record<string, Capability>
  latency_ms?: number
  credential_ref?: string
  generation?: ConnectionGeneration
}
